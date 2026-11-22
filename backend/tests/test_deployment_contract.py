from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
DEPLOY_IMAGE = REPO / "infra" / "scripts" / "deploy_image.sh"


def test_deploy_sh_is_the_only_deployment_definition():
    for stale in ("cloudrun-service.yaml", "deploy-yaml.sh", "redeploy-only.sh"):
        assert not (BACKEND / stale).exists()
    assert not list(BACKEND.glob("cloudrun-*.yaml"))


def test_worker_job_gets_its_timeout_and_can_dispatch_continuations():
    script = DEPLOY_IMAGE.read_text(encoding="utf-8")
    worker = script[script.index("deploy_worker_job() {"):]
    worker = worker[:worker.index("\n}\n")]

    assert '--task-timeout="${WORKER_TASK_TIMEOUT}"' in worker
    assert "CLOUD_RUN_TASK_TIMEOUT=${WORKER_TASK_TIMEOUT}" in worker
    assert "WORKER_JOB_NAME=${WORKER_JOB_NAME}" in worker
    assert '--max-retries="${WORKER_MAX_RETRIES}"' in worker
    assert 'WORKER_MAX_RETRIES="0"' in script


def test_skip_build_only_skips_the_image_build():
    script = DEPLOY_IMAGE.read_text(encoding="utf-8")
    main = script[script.index("\nmain() {"):]

    assert "--skip-build) SKIP_BUILD=\"true\"" in script
    assert main.index('if [ "${SKIP_BUILD}" == "true" ]') < main.index("build_and_push")
    assert main.index("build_and_push") < main.index("deploy_to_cloud_run") < main.index("deploy_worker_job")


def test_deploy_sh_delegates_to_the_shared_deploy_script():
    wrapper = (BACKEND / "deploy.sh").read_text(encoding="utf-8")
    assert "infra/scripts/deploy_image.sh" in wrapper
    assert "gcloud run" not in wrapper


def test_images_are_immutable_and_shared_by_service_and_job():
    script = DEPLOY_IMAGE.read_text(encoding="utf-8")
    for path in (DEPLOY_IMAGE, BACKEND / "cloudbuild.yaml", BACKEND / "deploy.sh", REPO / "infra/scripts/rollback.sh"):
        # Secret versions stay :latest on purpose; only image references must be pinned.
        assert "ai-subs-backend:latest" not in path.read_text(encoding="utf-8"), path
    assert 'IMAGE_REPO="${REGION}-docker.pkg.dev/${PROJECT_ID}/ai-subs-repo/ai-subs-backend"' in script
    assert "rev-parse --short=12 HEAD" in script
    assert 'IMAGE_TAG="${sha}-dirty"' in script
    for function in ("deploy_to_cloud_run() {", "deploy_worker_job() {"):
        body = script[script.index(function):]
        body = body[:body.index("\n}\n")]
        assert '--image="${IMAGE_REF}"' in body


def test_a_dirty_tree_is_refused_before_any_gcloud_call():
    main = DEPLOY_IMAGE.read_text(encoding="utf-8")
    main = main[main.index("\nmain() {"):]
    assert main.index("resolve_tag") < main.index("check_prerequisites")


def test_unbuilt_cloud_tasks_plan_is_archived_as_superseded():
    assert not (REPO / "docs/SCALABILITY_PLAN.md").exists()
    archived = (REPO / "docs/archive/SCALABILITY_PLAN.md").read_text(encoding="utf-8")
    assert "Superseded" in archived[:400]


def test_docs_do_not_reference_removed_deployment_files():
    for relative in (
        "README.md", "backend/DEPLOYMENT.md", "backend/QUICKSTART.md",
        "docs/ARCHITECTURE.md", "docs/GCP_OPERATIONS.md",
    ):
        text = (REPO / relative).read_text(encoding="utf-8")
        assert "deploy-yaml.sh" not in text
        assert "redeploy-only.sh" not in text
        assert "docs/SCALABILITY_PLAN.md" not in text
    assert "Why not Kubernetes" in (REPO / "docs/ARCHITECTURE.md").read_text(encoding="utf-8")


def _hub_pin(text):
    import re
    match = re.search(r"huggingface-hub==([\w.]+)", text)
    assert match, "huggingface-hub must be pinned"
    return match.group(1)


def test_model_fetch_layer_uses_the_runtime_huggingface_hub_version():
    # Fetch runs before requirements.txt; a different hub version could write a cache layout the runtime can't read.
    dockerfile = (BACKEND / "Dockerfile").read_text()
    assert _hub_pin(dockerfile) == _hub_pin((BACKEND / "requirements.txt").read_text())


def test_download_models_imports_only_stdlib_and_huggingface_hub():
    import ast
    import sys

    tree = ast.parse((BACKEND / "download_models.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module.split(".")[0])
    assert imported - set(sys.stdlib_module_names) == {"huggingface_hub"}


def test_transformers_reads_the_cache_snapshot_download_writes():
    # TRANSFORMERS_CACHE overrides HF_HOME/hub in transformers 4.x, so the baked
    # models would be invisible offline (build a27d789c failed this way).
    for name in ("Dockerfile", "download_models.py", "verify_models.py", "deploy.sh"):
        assert "TRANSFORMERS_CACHE" not in (BACKEND / name).read_text(encoding="utf-8"), name


def test_models_are_fetched_before_requirements_and_verified_after():
    lines = (BACKEND / "Dockerfile").read_text().splitlines()

    def index_of(fragment):
        return next(i for i, line in enumerate(lines) if fragment in line)

    fetch = index_of("python /tmp/models/download_models.py")
    torch = index_of("pip install --no-cache-dir torch==")
    requirements = index_of("COPY requirements.txt")
    verify = index_of("python /tmp/models/verify_models.py")
    app_copy = index_of("COPY . .")
    assert fetch < torch < requirements < verify < app_copy


def test_cloud_build_enables_inline_layer_cache():
    cloudbuild = (BACKEND / "cloudbuild.yaml").read_text()
    assert "BUILDKIT_INLINE_CACHE=1" in cloudbuild
    assert "DOCKER_BUILDKIT=1" in cloudbuild
    assert "--cache-from=" in cloudbuild


def _requirement_lines(path):
    lines = []
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def _canonical(name):
    import re
    return re.sub(r"[-_.]+", "-", name).lower()


def _constraint_pins():
    pins = {}
    for line in _requirement_lines(BACKEND / "constraints.txt"):
        name, version = line.split("==")
        pins[_canonical(name)] = version
    return pins


# Installed by the Dockerfile's own torch step from the cu126 index.
_TORCH_STACK = {"torch", "torchaudio"}


def test_requirements_install_uses_the_constraints_lock():
    # Without -c, any requirements.txt edit re-resolves every unpinned package to its newest release.
    dockerfile = (BACKEND / "Dockerfile").read_text()
    assert "COPY requirements.txt constraints.txt ./" in dockerfile
    assert "pip install --no-cache-dir -r requirements.txt -c constraints.txt" in dockerfile


def test_every_direct_requirement_is_locked_to_a_compatible_version():
    import re

    pins = _constraint_pins()
    for requirement in _requirement_lines(BACKEND / "requirements.txt"):
        name = _canonical(re.split(r"[<>=!~\[;\s]", requirement, maxsplit=1)[0])
        if name in _TORCH_STACK:
            continue
        assert name in pins, f"{name} is not in constraints.txt"
        exact = re.search(r"==\s*([\w.+]+)", requirement)
        if exact:
            assert pins[name] == exact.group(1), f"{name}: requirements.txt pins {exact.group(1)}, constraints.txt {pins[name]}"



_LOCAL_SECRETS = (".env.*", "api-key-transcribe", "*.key", "*.pem", "local_data/")


def test_build_context_excludes_local_secrets_and_data():
    # .gcloudignore pulls these in through #!include:.gitignore; .dockerignore has no include.
    assert "#!include:.gitignore" in (BACKEND / ".gcloudignore").read_text()
    for name in (".gitignore", ".dockerignore"):
        lines = (BACKEND / name).read_text().splitlines()
        for pattern in _LOCAL_SECRETS:
            assert pattern in lines, f"{name} must exclude {pattern}"


def test_image_swaps_in_gpu_onnxruntime_and_headless_opencv_from_the_lock():
    dockerfile = (BACKEND / "Dockerfile").read_text()
    assert "pip uninstall -y opencv-python onnxruntime" in dockerfile
    assert "pip install --no-cache-dir --no-deps -c constraints.txt opencv-python-headless onnxruntime-gpu" in dockerfile
    assert "onnxruntime-gpu" not in (BACKEND / "requirements.txt").read_text()
    for package in ("build-essential", "libgl1-mesa-glx", "python3-dev"):
        assert package not in dockerfile


def test_cuda_libraries_come_from_torch_wheels():
    # The cudnn-runtime base duplicated ~2 GB of CUDA libraries torch's cu126 wheels already ship.
    dockerfile = (BACKEND / "Dockerfile").read_text()
    assert "FROM nvidia/cuda:12.6.3-base-ubuntu22.04" in dockerfile
    assert "/etc/ld.so.conf.d/nvidia-pip.conf" in dockerfile
    assert "Unresolved CUDA libraries" in dockerfile
