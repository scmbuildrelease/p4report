from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import pytest
from openpyxl import load_workbook

from p4report.config import AppConfig
from p4report.email_sender import EmailConfigurationError, build_message, send_report
from p4report.excel_report import write_report
from p4report.mock_p4_client import MockP4Client
from p4report.models import Changelist, Employee
from p4report.statistics import calculate_statistics
from p4report.user_loader import UserListError, load_users


def test_user_loader_comments_blank_duplicate_and_invalid(tmp_path):
    path = tmp_path / "users.txt"
    path.write_text("# heading\n\nA Person|a@example.com|a\nB Person|b@example.com|b\n")
    assert [u.username for u in load_users(path)] == ["a", "b"]
    path.write_text("A|a@example.com|a\nB|b@example.com|a\n")
    with pytest.raises(UserListError, match="duplicate"):
        load_users(path)
    path.write_text("bad record\n")
    with pytest.raises(UserListError, match="Line 1"):
        load_users(path)
    path.write_text("A|bad|a\n")
    with pytest.raises(UserListError, match="email"):
        load_users(path)


def test_mock_adapter_relative_records(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(json.dumps([{"change": 1, "user": "ghost", "days_ago": 2,
                                 "hour": 7, "description": "demo", "files": ["//x"]}]))
    now = datetime(2025, 3, 12, 12, tzinfo=ZoneInfo("UTC"))
    changes = MockP4Client(path).get_changelists(now)
    assert changes[0].timestamp == datetime(2025, 3, 10, 7, tzinfo=ZoneInfo("UTC"))
    assert changes[0].user == "ghost"


def test_statistics_calendar_timezone_sort_zero_and_unmapped():
    zone = ZoneInfo("America/Los_Angeles")
    employees = [Employee("Zed", "z@example.com", "z"), Employee("Amy", "a@example.com", "a"),
                 Employee("Zero", "0@example.com", "zero")]
    now = datetime(2025, 1, 1, 7, tzinfo=ZoneInfo("UTC"))  # Dec 31 local, Tuesday
    local = now.astimezone(zone)
    changes = [
        Changelist(1, "z", local.replace(hour=0), "week edge", ("//a",)),
        Changelist(2, "z", local.replace(hour=23), "same day", ("//b",)),
        Changelist(3, "a", datetime(2024, 12, 1, tzinfo=zone), "month", ("//c",)),
        Changelist(4, "a", datetime(2024, 1, 2, tzinfo=zone), "year", ("//d",)),
        Changelist(5, "z", datetime(2025, 1, 1, 0, tzinfo=zone), "future", ("//e",)),
        Changelist(6, "gone", local, "unknown", ("//f",)),
    ]
    stats = calculate_statistics(employees, changes, now, zone)
    assert stats.weekly_total == 3
    assert stats.monthly_total == 4
    assert stats.yearly_total == 5
    assert stats.zero_weekly == 2
    assert len(stats.unmapped) == 1
    assert [x.employee.name for x in stats.weekly] == ["Zed", "Amy", "Zero"]
    assert stats.weekly[0].count == 2
    assert stats.period_start.weekday() == 0


def test_statistics_boundaries_monday_sunday_and_year():
    zone = ZoneInfo("UTC")
    emp = Employee("A", "a@example.com", "a")
    now = datetime(2024, 1, 7, 23, 59, tzinfo=zone)  # Sunday
    changes = [Changelist(i, "a", stamp, "d", ()) for i, stamp in enumerate([
        datetime(2024, 1, 1, tzinfo=zone), datetime(2024, 1, 7, 23, 59, tzinfo=zone),
        datetime(2023, 12, 31, 23, 59, tzinfo=zone)], 1)]
    stats = calculate_statistics([emp], changes, now, zone)
    assert stats.weekly_total == 2
    assert stats.monthly_total == 2
    assert stats.yearly_total == 2


def test_excel_has_expected_sheets_rows_and_styles(tmp_path):
    users = [Employee("A", "a@example.com", "a"), Employee("Z", "z@example.com", "z")]
    zone = ZoneInfo("UTC")
    now = datetime(2025, 6, 18, 10, tzinfo=zone)
    stats = calculate_statistics(users, [Changelist(42, "a", now, "description", ("//foo",)),
                                         Changelist(43, "unknown", now, "orphan", ())], now, zone)
    path = write_report(stats, tmp_path / "demo.xlsx", "UTC")
    wb = load_workbook(path, data_only=True)
    assert wb.sheetnames == ["Executive Summary", "Weekly Statistics", "Monthly Statistics",
                             "Yearly Statistics", "Changelist Details", "Unmapped Users"]
    assert wb["Weekly Statistics"].max_row == 3
    assert wb["Weekly Statistics"]["E2"].value == 1
    assert wb["Weekly Statistics"]["E3"].value == 0
    assert wb["Unmapped Users"].max_row == 2
    assert wb["Executive Summary"]["B6"].value == 2
    wb.close()


def test_email_dry_run_missing_and_attachment(tmp_path):
    emp = Employee("A", "a@example.com", "a")
    now = datetime(2025, 1, 1, tzinfo=ZoneInfo("UTC"))
    stats = calculate_statistics([emp], [], now, ZoneInfo("UTC"))
    path = tmp_path / "x.xlsx"
    path.write_bytes(b"synthetic workbook bytes")
    assert send_report(path, stats, {"SEND_EMAIL": "false"}) is False
    with pytest.raises(EmailConfigurationError):
        send_report(path, stats, {"SEND_EMAIL": "true"})
    msg = build_message(path, stats, "recipient@example.com", "sender@example.com")
    attachment = list(msg.iter_attachments())[0]
    assert attachment.get_filename() == "x.xlsx"
    assert attachment.get_payload(decode=True) == b"synthetic workbook bytes"


def test_email_send_mock_and_failure(tmp_path, monkeypatch):
    from p4report import email_sender
    emp = Employee("A", "a@example.com", "a")
    now = datetime(2025, 1, 1, tzinfo=ZoneInfo("UTC"))
    stats = calculate_statistics([emp], [], now, ZoneInfo("UTC"))
    path = tmp_path / "x.xlsx"
    path.write_bytes(b"workbook")
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout): calls.append((host, port, timeout))
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def starttls(self): calls.append("tls")
        def login(self, username, password): calls.append((username, password))
        def send_message(self, msg): calls.append(msg["To"])

    monkeypatch.setattr(email_sender.smtplib, "SMTP", FakeSMTP)
    env = {"SEND_EMAIL": "true", "SMTP_HOST": "smtp.local", "SMTP_PORT": "587",
           "SMTP_USERNAME": "user", "SMTP_PASSWORD": "not-logged", "SMTP_FROM": "from@example.com"}
    assert send_report(path, stats, env)
    assert calls[-1] == "aaa@example.com"

    class BrokenSMTP(FakeSMTP):
        def send_message(self, msg): raise OSError("delivery failed")
    monkeypatch.setattr(email_sender.smtplib, "SMTP", BrokenSMTP)
    with pytest.raises(OSError, match="delivery failed"):
        send_report(path, stats, env)


def test_config_timezone_error():
    with pytest.raises(ValueError, match="Unknown"):
        AppConfig(timezone="Not/A_Zone").zone()


def test_cli_dry_run_and_invalid_timezone(tmp_path, monkeypatch, capsys):
    from p4report import cli

    config = AppConfig(userlist=Path(__file__).parents[1] / "data" / "userlist.txt",
                       mock_data=Path(__file__).parents[1] / "data" / "mock_p4_data.json",
                       reports_dir=tmp_path)
    monkeypatch.setattr(cli, "AppConfig", lambda timezone: AppConfig(
        userlist=config.userlist, mock_data=config.mock_data,
        reports_dir=config.reports_dir, timezone=timezone))
    assert cli.main(["--dry-run"]) == 0
    assert list(tmp_path.glob("p4report_*.xlsx"))
    assert "Email skipped" in capsys.readouterr().out
    assert cli.main(["--timezone", "Invalid/Timezone"]) == 1
