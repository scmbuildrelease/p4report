"""SMTP delivery with explicit opt-in and safe failure reporting."""
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
from .statistics import ReportStats


class EmailConfigurationError(ValueError):
    """SMTP configuration is absent or incomplete."""


def build_message(report_path: Path, stats: ReportStats, recipient: str, sender: str) -> EmailMessage:
    date = stats.generated_at.strftime("%Y-%m-%d")
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = f"Weekly Perforce Changelist Activity Report - {date}"
    msg.set_content(
        "Hello,\n\n"
        f"Reporting period: {stats.period_start:%Y-%m-%d} through {stats.period_end:%Y-%m-%d}.\n"
        f"Employees: {len(stats.weekly)}. Weekly, monthly, and yearly changelists: "
        f"{stats.weekly_total}, {stats.monthly_total}, and {stats.yearly_total}.\n"
        "The Excel workbook is attached. This report uses synthetic demonstration data.\n"
    )
    msg.add_attachment(report_path.read_bytes(), maintype="application",
                       subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       filename=report_path.name)
    return msg


def send_report(report_path: Path, stats: ReportStats, environ=None) -> bool:
    """Send using STARTTLS; return False if opt-in is absent, raise on failures."""
    env = os.environ if environ is None else environ
    if env.get("SEND_EMAIL", "").lower() not in {"1", "true", "yes"}:
        return False
    required = ("SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM")
    missing = [key for key in required if not env.get(key)]
    if missing:
        raise EmailConfigurationError("Missing SMTP configuration: " + ", ".join(missing))
    recipient = env.get("REPORT_RECIPIENT", "aaa@example.com")
    msg = build_message(report_path, stats, recipient, env["SMTP_FROM"])
    with smtplib.SMTP(env["SMTP_HOST"], int(env["SMTP_PORT"]), timeout=30) as smtp:
        smtp.starttls()
        smtp.login(env["SMTP_USERNAME"], env["SMTP_PASSWORD"])
        smtp.send_message(msg)
    return True
