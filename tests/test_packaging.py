"""A regular (non-editable) install must work from any directory."""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_requirements_exclude_dev_tools():
    runtime = (ROOT / "requirements.txt").read_text().lower()
    for tool in ("pytest", "ruff", "mypy", "-e ."):
        assert tool not in runtime


@pytest.mark.skipif(importlib.util.find_spec("setuptools") is None, reason="setuptools needed to build")
def test_regular_install_runs_from_any_directory(tmp_path):
    target, workdir = tmp_path / "site", tmp_path / "elsewhere"
    workdir.mkdir()
    build = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--no-deps", "--no-build-isolation",
                            "--target", str(target), str(ROOT)], capture_output=True, text=True, check=False,
                           cwd=tmp_path)
    assert build.returncode == 0, build.stderr
    assert (target / "p4report" / "data" / "userlist.txt").exists()
    assert (target / "p4report" / "data" / "mock_p4_data.json").exists()
    assert (target / "p4report" / "py.typed").exists()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SMTP_", "SEND_EMAIL", "REPORT_"))}
    env["PYTHONPATH"] = str(target)
    result = subprocess.run([sys.executable, "-m", "p4report", "--as-of", "2026-11-23T09:00", "--dry-run"],
                            capture_output=True, text=True, env=env, cwd=workdir, check=False)
    assert result.returncode == 0, result.stderr
    assert "week: 6 mapped + 1 unmapped = 7" in result.stdout
    assert (workdir / "reports" / "p4report_2026-11-23.xlsx").exists()
