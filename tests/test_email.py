import smtplib
import ssl
from datetime import datetime

import pytest

from p4report.email_sender import (
    PLACEHOLDER_RECIPIENT,
    EmailConfigurationError,
    build_message,
    is_placeholder_address,
    send_report,
)
from p4report.statistics import calculate_statistics

from conftest import LA, SMTP_ENV, cl, emp

AS_OF = datetime(2026, 11, 23, 9, tzinfo=LA)


@pytest.fixture
def stats():
    changes = [cl(1, "a", datetime(2026, 11, 17, tzinfo=LA)), cl(2, "ghost", datetime(2026, 11, 18, tzinfo=LA)),
               cl(3, "a", datetime(2026, 11, 23, 1, tzinfo=LA))]
    return calculate_statistics([emp("Amy", "a")], changes, AS_OF, LA)


@pytest.fixture
def report(tmp_path):
    path = tmp_path / "p4report_2026-11-23.xlsx"
    path.write_bytes(b"PK\x03\x04 synthetic workbook bytes")
    return path


def test_message_subject_body_and_attachment(report, stats):
    msg = build_message(report, stats, "manager@corp-demo.net", "reports@corp-demo.net")
    assert msg["Subject"] == "Weekly Perforce Changelist Activity Report - 2026-11-23"
    assert (msg["To"], msg["From"]) == ("manager@corp-demo.net", "reports@corp-demo.net")
    body = msg.get_body(("plain",)).get_content()
    # Same definitions as the workbook: week 1+1, month 2+1, year 2+1.
    assert "Weekly (2026-11-16 00:00 to 2026-11-23 00:00, end exclusive): 1 mapped, 1 unmapped, 2 total" in body
    assert "Monthly (2026-11-01 00:00 to 2026-11-23 09:00, end exclusive): 2 mapped, 1 unmapped, 3 total" in body
    assert "Yearly (2026-01-01 00:00 to 2026-11-23 09:00, end exclusive): 2 mapped, 1 unmapped, 3 total" in body
    [attachment] = list(msg.iter_attachments())
    assert attachment.get_content_type() == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert attachment.get_filename() == "p4report_2026-11-23.xlsx"
    assert attachment.get_payload(decode=True) == report.read_bytes()


@pytest.mark.parametrize("value", ["", "false", "0", "no", "off"])
def test_disabled_unless_explicitly_opted_in(report, stats, fake_smtp, value):
    smtp = fake_smtp()
    assert send_report(report, stats, {**SMTP_ENV, "SEND_EMAIL": value}) is False
    assert smtp.instances == []


def test_starttls_uses_verifying_context_before_login(report, stats, fake_smtp):
    smtp = fake_smtp()
    assert send_report(report, stats, SMTP_ENV) is True
    [conn] = smtp.instances
    assert [c[0] for c in conn.calls] == ["connect", "starttls", "login", "send"]
    context = conn.calls[1][1]
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert (conn.host, conn.port, conn.timeout) == ("smtp.mail.test-provider.net", 587, 30)
    assert conn.calls[3] == ("send", "manager@corp-demo.net")
    assert conn.closed


def test_port_465_uses_implicit_tls_with_verifying_context(report, stats, fake_smtp):
    smtp = fake_smtp()
    send_report(report, stats, {**SMTP_ENV, "SMTP_PORT": "465"})
    [conn] = smtp.instances
    assert conn.ssl_context.verify_mode == ssl.CERT_REQUIRED and conn.ssl_context.check_hostname
    assert "starttls" not in [c[0] for c in conn.calls]


@pytest.mark.parametrize("recipient", [PLACEHOLDER_RECIPIENT, "user@example.com", "a@example.org",
                                       "b@mail.example.net", "c@EXAMPLE.COM", "d@host.test", "e@x.invalid"])
def test_placeholder_recipients_are_never_contacted(report, stats, fake_smtp, recipient):
    smtp = fake_smtp()
    with pytest.raises(EmailConfigurationError, match="placeholder"):
        send_report(report, stats, {**SMTP_ENV, "REPORT_RECIPIENT": recipient})
    assert smtp.instances == []


def test_lookalike_domains_are_not_placeholders():
    assert not is_placeholder_address("boss@example.company.net")
    assert not is_placeholder_address("boss@notexample.com")


@pytest.mark.parametrize(("override", "needle"), [
    ({"REPORT_RECIPIENT": ""}, "REPORT_RECIPIENT"),
    ({"SMTP_HOST": " "}, "SMTP_HOST"),
    ({"SMTP_PASSWORD": ""}, "SMTP_PASSWORD"),
    ({"SMTP_PORT": "abc"}, "SMTP_PORT must be an integer from 1 to 65535, got 'abc'"),
    ({"SMTP_PORT": "70000"}, "SMTP_PORT must be an integer"),
    ({"REPORT_RECIPIENT": "not-an-address"}, "REPORT_RECIPIENT is not a valid email address"),
    ({"SMTP_FROM": "bad@"}, "SMTP_FROM is not a valid email address"),
])
def test_configuration_errors(report, stats, fake_smtp, override, needle):
    smtp = fake_smtp()
    with pytest.raises(EmailConfigurationError) as info:
        send_report(report, stats, {**SMTP_ENV, **override})
    assert needle in str(info.value)
    assert SMTP_ENV["SMTP_PASSWORD"] not in str(info.value)
    assert smtp.instances == []


@pytest.mark.parametrize(("fail_on", "error"), [
    ("connect", ConnectionRefusedError),
    ("login", smtplib.SMTPAuthenticationError),
    ("send", smtplib.SMTPDataError),
])
def test_smtp_failures_propagate_without_leaking_password(report, stats, fake_smtp, fail_on, error):
    fake_smtp(fail_on=fail_on)
    with pytest.raises(error) as info:
        send_report(report, stats, SMTP_ENV)
    assert SMTP_ENV["SMTP_PASSWORD"] not in str(info.value)


def test_refused_recipient_is_a_failure(report, stats, fake_smtp):
    fake_smtp(refused={"manager@corp-demo.net": (550, b"no such user")})
    with pytest.raises(smtplib.SMTPRecipientsRefused):
        send_report(report, stats, SMTP_ENV)
