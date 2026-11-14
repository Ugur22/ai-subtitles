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
