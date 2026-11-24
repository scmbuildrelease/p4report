import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from openpyxl import load_workbook

from p4report import cli, email_sender

from conftest import LA, SMTP_ENV, cl

SCHEDULED = datetime(2026, 11, 23, 17, tzinfo=UTC)  # Monday cron tick
SRC = Path(__file__).resolve().parents[1] / "src"


@pytest.fixture(autouse=True)
def no_email_env(monkeypatch):
    for key in SMTP_ENV:
        monkeypatch.delenv(key, raising=False)


def run(argv, tmp_path, **kwargs):
    return cli.main([*argv, "--output-dir", str(tmp_path)], now=kwargs.pop("now", SCHEDULED), **kwargs)


def test_default_run_uses_bundled_data_and_never_emails(tmp_path, capsys, fake_smtp):
    smtp = fake_smtp()
    assert run([], tmp_path) == 0
    out = capsys.readouterr().out
    # Bundled demo data, independently counted for Monday 2026-11-23 09:00 PST (see README table).
    assert ("week: 6 mapped + 1 unmapped = 7 | month: 8 mapped + 1 unmapped = 9 | "
            "year: 11 mapped + 2 unmapped = 13") in out
    assert "Email skipped" in out
    assert (tmp_path / "p4report_2026-11-23.xlsx").exists()
    assert smtp.instances == []


def test_bundled_demo_workbook_matches_hand_count(tmp_path):
    assert run(["--dry-run"], tmp_path) == 0
    wb = load_workbook(tmp_path / "p4report_2026-11-23.xlsx")
    ws = wb["Weekly Statistics"]
    h = next(c.row for c in ws["A"] if c.value == "Rank")
    rows = [(r[0].value, r[1].value, r[4].value) for r in ws.iter_rows(min_row=h + 1)]
    assert rows == [(1, "Alex Example", 3), (2, "Blair Sample", 2), (3, "Drew Fiction", 1),
                    (4, "Casey Demo", 0), (4, "Emery Placeholder", 0)]
    details = wb["Changelist Details"]
    assert details.max_row - 1 == 13  # 14 records, #41014 (420 days ago) is outside the fetched range
    unmapped = wb["Unmapped Users"]
    assert [(r[0].value, r[1].value, r[3].value) for r in unmapped.iter_rows(min_row=2)] == [
        ("build-bot", 0, 1), ("ghost-demo", 1, 1)]


def test_dry_run_overrides_send_email(tmp_path, capsys, fake_smtp, monkeypatch):
    for key, value in SMTP_ENV.items():
        monkeypatch.setenv(key, value)
    smtp = fake_smtp()
    assert run(["--send-email", "--dry-run"], tmp_path) == 0
    assert smtp.instances == []
    assert "Email skipped" in capsys.readouterr().out


def test_send_email_flag_without_env_opt_in_skips(tmp_path, capsys, fake_smtp):
    smtp = fake_smtp()
    assert run(["--send-email"], tmp_path) == 0
    assert "SEND_EMAIL is not enabled" in capsys.readouterr().out
    assert smtp.instances == []


def test_send_email_success(tmp_path, capsys, fake_smtp, monkeypatch):
    for key, value in SMTP_ENV.items():
        monkeypatch.setenv(key, value)
    smtp = fake_smtp()
    assert run(["--send-email"], tmp_path) == 0
    assert capsys.readouterr().out.strip().endswith("Email sent.")
    [conn] = smtp.instances
    [msg] = conn.sent
    [attachment] = list(msg.iter_attachments())
    assert attachment.get_payload(decode=True) == (tmp_path / "p4report_2026-11-23.xlsx").read_bytes()


@pytest.mark.parametrize("fail_on", ["connect", "login", "send"])
def test_workbook_exists_before_email_and_survives_smtp_failure(tmp_path, capsys, monkeypatch, fail_on, fake_smtp):
    for key, value in SMTP_ENV.items():
        monkeypatch.setenv(key, value)
    smtp_cls = fake_smtp(fail_on=fail_on)
    seen_before_connect = []
    original_init = smtp_cls.__init__

    def init(self, *args, **kwargs):
        seen_before_connect.append((tmp_path / "p4report_2026-11-23.xlsx").exists())
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(smtp_cls, "__init__", init)
    assert run(["--send-email"], tmp_path) == 1
    captured = capsys.readouterr()
    assert seen_before_connect == [True]
    assert (tmp_path / "p4report_2026-11-23.xlsx").exists()
    assert "Email sent" not in captured.out
    assert "email delivery error" in captured.err and "workbook was kept" in captured.err
    assert SMTP_ENV["SMTP_PASSWORD"] not in captured.out + captured.err


def test_placeholder_recipient_rejected_from_cli(tmp_path, capsys, monkeypatch, fake_smtp):
    for key, value in {**SMTP_ENV, "REPORT_RECIPIENT": "aaa@example.com"}.items():
        monkeypatch.setenv(key, value)
    smtp = fake_smtp()
    assert run(["--send-email"], tmp_path) == 1
    assert "placeholder" in capsys.readouterr().err
    assert smtp.instances == []


@pytest.mark.parametrize(("argv", "needle"), [
    (["--timezone", "Mars/Base"], "Unknown reporting timezone 'Mars/Base'"),
    (["--timezone", ""], "Unknown reporting timezone"),
    (["--userlist", "missing-users.txt"], "missing-users.txt"),
    (["--data", "missing.json"], "missing.json"),
])
def test_invalid_inputs_fail_with_useful_message(tmp_path, capsys, argv, needle):
    assert run(argv, tmp_path) == 1
    err = capsys.readouterr().err
    assert err.startswith("p4report failed: report generation error:")
    assert needle in err
    assert list(tmp_path.glob("*.xlsx")) == []


def test_path_overrides_resolved_against_cwd(tmp_path, monkeypatch, capsys):
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "u.txt").write_text("Solo Dev|solo@example.com|solo\n")
    (tmp_path / "in" / "d.json").write_text(
        '[{"change": 9, "user": "solo", "timestamp": "2026-11-18T12:00:00-08:00", "description": "x", "files": []}]')
    monkeypatch.chdir(tmp_path)
    code = cli.main(["--userlist", "in/u.txt", "--data", "in/d.json", "--output-dir", "out",
                     "--as-of", "2026-11-23T09:00", "--timezone", "America/Los_Angeles"])
    assert code == 0
    assert "week: 1 mapped + 0 unmapped = 1" in capsys.readouterr().out
    assert (tmp_path / "out" / "p4report_2026-11-23.xlsx").exists()


def test_timezone_option_changes_file_date_and_buckets(tmp_path, capsys):
    assert run(["--timezone", "Asia/Tokyo"], tmp_path) == 0
    assert (tmp_path / "p4report_2026-11-24.xlsx").exists()  # 17:00 UTC Monday is Tuesday 02:00 JST


def test_injected_client_receives_report_range(tmp_path, capsys):
    calls = []

    class FakeClient:
        def __init__(self, data_path, as_of):
            calls.append(("init", as_of))

        def get_changelists(self, start, end):
            calls.append(("range", start, end))
            return [cl(500, "alex", datetime(2026, 11, 20, 12, tzinfo=LA)),
                    cl(501, "nobody", datetime(2026, 11, 21, 12, tzinfo=LA))]

    assert run([], tmp_path, client_factory=FakeClient) == 0
    assert calls == [("init", SCHEDULED.astimezone(LA)),
                     ("range", datetime(2026, 1, 1, tzinfo=LA), datetime(2026, 11, 23, 9, tzinfo=LA))]
    assert "week: 1 mapped + 1 unmapped = 2" in capsys.readouterr().out


def test_previous_week_range_reaches_into_last_year(tmp_path):
    starts = []

    class FakeClient:
        def __init__(self, *_):
            pass

        def get_changelists(self, start, end):
            starts.append(start)
            return []

    run([], tmp_path, client_factory=FakeClient, now=datetime(2026, 1, 5, 17, tzinfo=UTC))
    assert starts == [datetime(2025, 12, 29, tzinfo=LA)]


def test_module_entry_point_and_output_order(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    for key in SMTP_ENV:
        env.pop(key, None)
    result = subprocess.run([sys.executable, "-m", "p4report", "--as-of", "2026-11-23T09:00",
                             "--output-dir", str(tmp_path), "--timezone", "UTC", "--dry-run"],
                            capture_output=True, text=True, env=env, cwd=tmp_path, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0].startswith("Workbook: ")
    bad = subprocess.run([sys.executable, "-m", "p4report", "--bogus"], capture_output=True, text=True,
                         env=env, cwd=tmp_path, check=False)
    assert bad.returncode == 2


def test_email_module_not_called_on_generation_failure(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(cli, "send_report", lambda *a: called.append(a))
    monkeypatch.setattr(email_sender.smtplib, "SMTP", lambda *a, **k: called.append(a))
    assert run(["--send-email", "--timezone", "Nope/Zone"], tmp_path) == 1
    assert called == []


def test_dunder_main_in_process(tmp_path, monkeypatch, capsys):
    import runpy
    monkeypatch.setattr(sys, "argv", ["p4report", "--dry-run", "--as-of", "2026-11-23T09:00",
                                      "--output-dir", str(tmp_path)])
    with pytest.raises(SystemExit) as info:
        runpy.run_module("p4report", run_name="__main__")
    assert info.value.code == 0
    assert "Workbook:" in capsys.readouterr().out
