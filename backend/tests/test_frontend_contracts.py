"""Source checks on frontend behaviour the frontend has no test runner for yet."""
import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"
JOBS = FRONTEND / "components" / "features" / "jobs"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_retry_button_uses_the_shared_api_client():
    card = _read(JOBS / "JobCard.tsx")
    handler = card[card.index("const retry = useMutation"):card.index("const cancel = useMutation")]

    # The auth cookie belongs to the API host; a same-origin fetch to /api lacks it.
    assert "mutationFn: () => retryJob(job.job_id, job.access_token)" in handler
    assert "fetch(" not in card
    assert "connection_lost:" in card


def test_delete_does_not_wait_for_the_server():
    panel = _read(JOBS / "JobPanel.tsx")
    card = _read(JOBS / "JobCard.tsx")
    card_delete = card[card.index("const handleDelete"):card.index("return (", card.index("const handleDelete"))]

    assert "await deleteJob" not in panel
    assert "await onDelete" not in card_delete
    assert "deleteJobPermanent" in _read(FRONTEND / "hooks" / "useJobTracker.ts")


def test_panel_and_page_share_one_job_list():
    upload = _read(FRONTEND / "components" / "features" / "transcription" / "TranscriptionUpload.tsx")

    assert "useJobTracker()" not in _read(JOBS / "JobPanel.tsx")
    assert "tracker={jobTracker}" in upload


def test_upload_sends_the_chosen_whisper_model():
    upload = _read(FRONTEND / "components" / "features" / "transcription" / "TranscriptionUpload.tsx")
    api = _read(FRONTEND / "services" / "api.ts")
    submit = upload[upload.index("backgroundJobSubmit.submit(file, {"):]
    assert "model: selectedModel," in submit[:submit.index("});")]
    body = api[api.index("const jobParams: JobSubmitParams = {"):]
    assert re.search(r"\bmodel\b,", body[:body.index("};")])


def test_a_running_job_asks_before_cancelling():
    card = _read(JOBS / "JobCard.tsx")
    assert 'confirmBeforeCancel={job.status === "processing"}' in card
    assert "isCancellableJobStatus(job.status)" in card
    assert "Stop this job?" in card


def test_frontend_and_backend_agree_on_which_jobs_can_be_cancelled():
    import re

    types = _read(FRONTEND / "types" / "job.ts")
    helper = types[types.index("export const isCancellableJobStatus"):]
    frontend = set(re.findall(r"status === '(\w+)'", helper[:helper.index(";")]))
    service = (FRONTEND.parents[1] / "backend" / "services" / "job_queue_service.py").read_text(encoding="utf-8")
    cancel = service[service.index("def cancel_job("):]
    backend = set(re.findall(r'"(\w+)"', re.search(r'if job\["status"\] not in \(([^)]*)\)', cancel).group(1)))
    assert frontend == backend == {"pending", "processing"}
