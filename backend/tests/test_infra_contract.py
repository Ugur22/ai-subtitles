"""Keep the deploy script and infra/terraform in step.

A secret mounted by the deploy script without a matching secretAccessor binding
fails only at revision start in production, so the lists are compared here.
"""
import re
import subprocess
import pytest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = REPO / "infra" / "scripts" / "deploy_image.sh"
TERRAFORM = REPO / "infra" / "terraform"


def _function_body(script: str, name: str) -> str:
    body = script[script.index(f"{name}() {{"):]
    return body[:body.index("\n}\n")]


def _mounted_secrets(function_name: str) -> set:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    name = {"deploy_to_cloud_run": "API_SECRETS", "deploy_worker_job": "WORKER_SECRETS"}[function_name]
    assert f'--set-secrets="^@^${{{name}}}"' in _function_body(script, function_name)
    chain = re.search(rf'^{name}="([^"]+)"', script, re.M).group(1)
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


@pytest.mark.parametrize("state,exit_code", [("ENABLED", 0), ("DISABLED", 1), ("", 1)])
def test_secret_preflight_checks_version_state(tmp_path, state, exit_code):
    gcloud = tmp_path / "gcloud"
    gcloud.write_text(f'#!/bin/sh\nprintf "%s\\n" "{state}"\n', encoding="utf-8")
    gcloud.chmod(0o755)
    command = f'source "{DEPLOY_SCRIPT}"; PATH="{tmp_path}:$PATH"; check_secrets'
    result = subprocess.run(["bash", "-c", command], capture_output=True, text=True)
    assert result.returncode == exit_code
    if exit_code:
        assert "supabase-service-key" in result.stderr


def test_runtime_service_accounts_are_created_by_terraform():
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    iam = (TERRAFORM / "iam.tf").read_text(encoding="utf-8")

    used = set(re.findall(r'(?:API|WORKER)_SERVICE_ACCOUNT="([a-z0-9-]+)@', script))
    created = set(re.findall(r'account_id\s*=\s*"([a-z0-9-]+)"', iam))
    assert used == {"ai-subs-api", "ai-subs-worker"}
    assert used <= created
    assert "-compute@developer.gserviceaccount.com" not in script


def test_terraform_never_holds_secret_values():
    for tf in TERRAFORM.glob("*.tf"):
        text = tf.read_text(encoding="utf-8")
        assert "google_secret_manager_secret_version" not in text, tf.name
        assert "secret_data" not in text, tf.name


def _script_value(name: str) -> str:
    return re.search(rf'^{name}="([^"]+)"', DEPLOY_SCRIPT.read_text(encoding="utf-8"), re.M).group(1)


def test_builds_run_as_the_terraform_deployer_in_its_staging_bucket():
    wif = (TERRAFORM / "wif.tf").read_text(encoding="utf-8")
    assert _script_value("DEPLOYER_SERVICE_ACCOUNT").startswith("ai-subs-deployer@")
    assert 'account_id   = "ai-subs-deployer"' in wif
    assert _script_value("BUILD_STAGING_BUCKET") == "gs://${PROJECT_ID}-build-staging"
    assert 'name                        = "${var.project_id}-build-staging"' in wif


def test_the_deployer_cannot_change_iam_policies_so_deploys_do_not_try():
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "--allow-unauthenticated \\" not in script
    wif = (TERRAFORM / "wif.tf").read_text(encoding="utf-8")
    assert "roles/run.admin" not in wif
    assert "google_service_account_key" not in wif

