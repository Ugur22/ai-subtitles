"""Keep the deploy script and infra/terraform in step.

A secret mounted by the deploy script without a matching secretAccessor binding
fails only at revision start in production, so the lists are compared here.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = REPO / "backend" / "deploy.sh"
TERRAFORM = REPO / "infra" / "terraform"


def _function_body(script: str, name: str) -> str:
    body = script[script.index(f"{name}() {{"):]
    return body[:body.index("\n}\n")]


def _mounted_secrets(function_name: str) -> set:
    body = _function_body(DEPLOY_SCRIPT.read_text(encoding="utf-8"), function_name)
    chain = re.search(r'--set-secrets="\^@\^([^"]+)"', body).group(1)
    return {entry.split("=", 1)[1].split(":", 1)[0] for entry in chain.split("@")}


def _terraform_default_list(variable: str) -> set:
    text = (TERRAFORM / "variables.tf").read_text(encoding="utf-8")
    block = text[text.index(f'variable "{variable}"'):]
    block = block[:block.index("\n}\n")]
    default = block[block.index("default"):]
    return set(re.findall(r'"([^"]+)"', default[:default.index("]")]))


def test_every_api_secret_has_an_accessor_binding():
    assert _mounted_secrets("deploy_to_cloud_run") == _terraform_default_list("api_secret_ids")


def test_every_worker_secret_has_an_accessor_binding():
    assert _mounted_secrets("deploy_worker_job") == _terraform_default_list("worker_secret_ids")


def test_runtime_service_accounts_are_created_by_terraform():
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    iam = (TERRAFORM / "iam.tf").read_text(encoding="utf-8")

    used = set(re.findall(r'_SERVICE_ACCOUNT="([a-z0-9-]+)@', script))
    created = set(re.findall(r'account_id\s*=\s*"([a-z0-9-]+)"', iam))
    assert used == {"ai-subs-api", "ai-subs-worker"}
    assert used <= created
    assert "-compute@developer.gserviceaccount.com" not in script


def test_terraform_never_holds_secret_values():
    for tf in TERRAFORM.glob("*.tf"):
        text = tf.read_text(encoding="utf-8")
        assert "google_secret_manager_secret_version" not in text, tf.name
        assert "secret_data" not in text, tf.name
