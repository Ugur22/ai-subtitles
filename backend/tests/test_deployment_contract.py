from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


def test_deploy_sh_is_the_only_deployment_definition():
    for stale in ("cloudrun-service.yaml", "deploy-yaml.sh", "redeploy-only.sh"):
        assert not (BACKEND / stale).exists()
    assert not list(BACKEND.glob("cloudrun-*.yaml"))


def test_worker_job_gets_its_timeout_and_can_dispatch_continuations():
    script = (BACKEND / "deploy.sh").read_text(encoding="utf-8")
    worker = script[script.index("deploy_worker_job() {"):]
    worker = worker[:worker.index("\n}\n")]

    assert '--task-timeout="${WORKER_TASK_TIMEOUT}"' in worker
    assert "CLOUD_RUN_TASK_TIMEOUT=${WORKER_TASK_TIMEOUT}" in worker
    assert "WORKER_JOB_NAME=${WORKER_JOB_NAME}" in worker
    assert '--max-retries="${WORKER_MAX_RETRIES}"' in worker
    assert 'WORKER_MAX_RETRIES="0"' in script


def test_skip_build_only_skips_the_image_build():
    script = (BACKEND / "deploy.sh").read_text(encoding="utf-8")
    main = script[script.index("\nmain() {"):]

    assert "--skip-build) SKIP_BUILD=\"true\"" in main
    assert main.index('if [ "${SKIP_BUILD}" == "true" ]') < main.index("build_and_push")
    assert main.index("build_and_push") < main.index("deploy_to_cloud_run") < main.index("deploy_worker_job")


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
