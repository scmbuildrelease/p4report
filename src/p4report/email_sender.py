"""SMTP delivery with explicit opt-in, verified TLS and safe failure reporting."""
from __future__ import annotations

import os
import smtplib
import ssl
from collections.abc import Mapping
from email.message import EmailMessage
from pathlib import Path

from .models import is_valid_email
from .statistics import ReportStats

PLACEHOLDER_RECIPIENT = "aaa@example.com"  # documentation placeholder only; never delivered to
# RFC 2606 / RFC 6761 reserved names that can never be real mailboxes.
RESERVED_DOMAINS = ("example.com", "example.org", "example.net")
RESERVED_TLDS = ("example", "test", "invalid", "localhost")
XLSX_SUBTYPE = "vnd.openxmlformats-officedocument.spreadsheetml.sheet"
IMPLICIT_TLS_PORT = 465


class EmailConfigurationError(ValueError):
    """SMTP configuration is absent, incomplete or unsafe."""


def email_enabled(environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return env.get("SEND_EMAIL", "").strip().lower() in {"1", "true", "yes"}


def is_placeholder_address(address: str) -> bool:
    domain = address.rsplit("@", 1)[-1].strip().lower().rstrip(".")
    return (any(domain == d or domain.endswith("." + d) for d in RESERVED_DOMAINS)
            or domain.rsplit(".", 1)[-1] in RESERVED_TLDS)


def _port(raw: str) -> int:
    try:
        port = int(raw)
    except ValueError:
        port = 0
    if not 1 <= port <= 65535:
        raise EmailConfigurationError(f"SMTP_PORT must be an integer from 1 to 65535, got {raw!r}")
    return port


def _period_line(label: str, mapped: int, unmapped: int, total: int, start: str, end: str) -> str:
    return (f"{label} ({start} to {end}, end exclusive): {mapped} mapped, "
            f"{unmapped} unmapped, {total} total changelists.")


def build_message(report_path: Path, stats: ReportStats, recipient: str, sender: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = f"Weekly Perforce Changelist Activity Report - {stats.generated_at:%Y-%m-%d}"
    lines = [_period_line(ps.period.title, ps.mapped, ps.unmapped, ps.total,
                          f"{ps.period.start:%Y-%m-%d %H:%M}", f"{ps.period.end:%Y-%m-%d %H:%M}")
             for ps in stats.periods]
    msg.set_content(
        "Hello,\n\n"
        f"Reporting timezone: {stats.timezone_name}. Employees: {stats.employee_count}.\n"
        + "\n".join(lines) + "\n"
        "Mapped changelists belong to employees in the directory; unmapped ones are listed on the "
        "Unmapped Users sheet.\n\n"
        "The Excel workbook is attached. This report uses synthetic demonstration data.\n"
    )
    msg.add_attachment(report_path.read_bytes(), maintype="application", subtype=XLSX_SUBTYPE,
                       filename=report_path.name)
    return msg


def send_report(report_path: Path, stats: ReportStats, environ: Mapping[str, str] | None = None) -> bool:
    """Deliver the workbook. Returns False when SEND_EMAIL is not enabled.

    Raises EmailConfigurationError for missing/unsafe settings and smtplib or
    OSError exceptions for connection, authentication and delivery failures.
    """
    env = os.environ if environ is None else environ
    if not email_enabled(env):
        return False
    required = ("SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM", "REPORT_RECIPIENT")
    missing = [key for key in required if not env.get(key, "").strip()]
    if missing:
        raise EmailConfigurationError("Missing SMTP configuration: " + ", ".join(missing))
    recipient, sender = env["REPORT_RECIPIENT"].strip(), env["SMTP_FROM"].strip()
    for label, address in (("REPORT_RECIPIENT", recipient), ("SMTP_FROM", sender)):
        if not is_valid_email(address):
            raise EmailConfigurationError(f"{label} is not a valid email address")
    if is_placeholder_address(recipient):
        raise EmailConfigurationError(
            f"REPORT_RECIPIENT {recipient!r} is a reserved placeholder address; configure a real recipient")
    port = _port(env["SMTP_PORT"])
    msg = build_message(report_path, stats, recipient, sender)
    context = ssl.create_default_context()  # CERT_REQUIRED + hostname checking
    smtp: smtplib.SMTP
    if port == IMPLICIT_TLS_PORT:
        smtp = smtplib.SMTP_SSL(env["SMTP_HOST"], port, timeout=30, context=context)
    else:
        smtp = smtplib.SMTP(env["SMTP_HOST"], port, timeout=30)
    with smtp:
        if port != IMPLICIT_TLS_PORT:
            smtp.starttls(context=context)
        smtp.login(env["SMTP_USERNAME"], env["SMTP_PASSWORD"])
        refused = smtp.send_message(msg)
    if refused:
        raise smtplib.SMTPRecipientsRefused(refused)
    return True
