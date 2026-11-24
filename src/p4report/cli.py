"""Command line entry point."""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from .config import DEFAULT_MOCK_DATA, DEFAULT_REPORTS_DIR, DEFAULT_TIMEZONE, DEFAULT_USERLIST, AppConfig
from .email_sender import email_enabled, send_report
from .excel_report import write_report
from .mock_p4_client import MockP4Client
from .p4_client import ClientFactory
from .statistics import ReportStats, calculate_statistics, reporting_periods
from .user_loader import load_users


def _out(message: str) -> None:
    print(message, flush=True)


def _err(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="p4report", description="Generate the synthetic Perforce activity report")
    parser.add_argument("--userlist", type=Path, default=DEFAULT_USERLIST,
                        help="employee directory name|email|p4_username (default: bundled demo file)")
    parser.add_argument("--data", type=Path, default=DEFAULT_MOCK_DATA,
                        help="mock Perforce JSON data (default: bundled demo file)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_REPORTS_DIR,
                        help="directory for the workbook, relative to the current directory (default: reports)")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE, help="reporting IANA timezone")
    parser.add_argument("--as-of", help="report reference time, ISO-8601; without an offset it is read in "
                                        "the reporting timezone (default: now)")
    parser.add_argument("--dry-run", action="store_true", help="never send email, even with --send-email")
    parser.add_argument("--send-email", action="store_true",
                        help="request SMTP delivery; SEND_EMAIL=true must also be set")
    return parser


def _summary(stats: ReportStats) -> str:
    parts = [f"{ps.period.key}: {ps.mapped} mapped + {ps.unmapped} unmapped = {ps.total}" for ps in stats.periods]
    return f"Employees: {stats.employee_count} | " + " | ".join(parts)


def main(argv: list[str] | None = None, *, client_factory: ClientFactory | None = None,
         now: datetime | None = None) -> int:
    """Run the report. ``client_factory`` and ``now`` allow injection in tests or private deployments."""
    args = _parser().parse_args(argv)
    try:
        config = AppConfig(args.userlist, args.data, args.output_dir, args.timezone).resolved()
        zone = config.zone()
        if now is None and args.as_of:
            now = datetime.fromisoformat(args.as_of)
            now = now if now.tzinfo else now.replace(tzinfo=zone)
        as_of = (now or datetime.now(zone)).astimezone(zone)
        users = load_users(config.userlist)
        start = min((p.start for p in reporting_periods(as_of, zone)), key=lambda d: d.astimezone(UTC))
        client = (client_factory or MockP4Client)(config.mock_data, as_of)
        stats = calculate_statistics(users, client.get_changelists(start, as_of), as_of, zone)
        output = write_report(stats, config.reports_dir / f"p4report_{as_of:%Y-%m-%d}.xlsx")
    except (OSError, ValueError) as exc:
        _err(f"p4report failed: report generation error: {exc}")
        return 1
    _out(f"Workbook: {output}\n{_summary(stats)}")
    if args.dry_run or not args.send_email:
        _out("Email skipped (dry run or --send-email not given).")
        return 0
    if not email_enabled():
        _out("Email skipped: SEND_EMAIL is not enabled.")
        return 0
    try:
        send_report(output, stats)
    except (OSError, ValueError) as exc:  # smtplib errors are OSError subclasses
        _err(f"p4report failed: email delivery error ({type(exc).__name__}): {exc}. "
             f"The workbook was kept at {output}")
        return 1
    _out("Email sent.")
    return 0
