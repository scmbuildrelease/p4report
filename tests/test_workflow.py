"""Static checks of the GitHub Actions workflow (it cannot be executed locally)."""
import re
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "weekly-report.yml"


@pytest.fixture(scope="module")
def wf():
    data = yaml.safe_load(WORKFLOW.read_text())
    data["on"] = data.pop(True)  # PyYAML reads the bare key `on` as boolean True
    return data


def test_triggers_and_schedule(wf):
    assert wf["on"]["schedule"] == [{"cron": "0 17 * * 1"}]
    dispatch = wf["on"]["workflow_dispatch"]["inputs"]["send_email"]
    assert dispatch["type"] == "boolean" and dispatch["default"] is False


def test_least_privilege_and_concurrency(wf):
    assert wf["permissions"] == {"contents": "read"}
    assert "group" in wf["concurrency"]
    for job in wf["jobs"].values():
        assert "permissions" not in job or job["permissions"] == {"contents": "read"}


def test_actions_pinned_to_full_commit_sha():
    uses = re.findall(r"uses:\s*(\S+)", WORKFLOW.read_text())
    assert uses
    for ref in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), ref


def test_report_job_gated_by_tests_and_runtime_only_install(wf):
    report = wf["jobs"]["report"]
    assert report["needs"] == "test"
    assert "schedule" in report["if"] and "workflow_dispatch" in report["if"]
    install = next(s["run"] for s in report["steps"] if "Install" in s.get("name", ""))
    assert "requirements.txt" in install and "requirements-dev" not in install and "-e" not in install


def test_email_default_off_and_secrets_only_via_env(wf):
    steps = wf["jobs"]["report"]["steps"]
    gen = next(s for s in steps if s.get("name", "").startswith("Generate"))
    env = gen["env"]
    assert "inputs.send_email" in env["SEND_EMAIL"] and "vars.SEND_EMAIL == 'true'" in env["SEND_EMAIL"]
    assert env["REPORT_RECIPIENT"] == "${{ vars.REPORT_RECIPIENT }}"  # no placeholder fallback
    assert "secrets." not in gen["run"]
    text = WORKFLOW.read_text()
    assert not re.search(r"echo .*secrets\.", text)


def test_artifact_uploaded_even_when_email_fails(wf):
    steps = wf["jobs"]["report"]["steps"]
    upload = next(s for s in steps if "upload-artifact" in s.get("uses", ""))
    assert upload["if"] == "always()"
    assert upload["with"]["path"] == "reports/*.xlsx"
    assert upload["with"]["retention-days"] == 30
    assert steps.index(upload) > steps.index(next(s for s in steps if s.get("name", "").startswith("Generate")))


def test_ci_job_runs_lint_types_and_tests(wf):
    runs = " ".join(s.get("run", "") for s in wf["jobs"]["test"]["steps"])
    for command in ("ruff check", "mypy", "pytest", "requirements-dev.txt"):
        assert command in runs
