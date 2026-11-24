"""Command line entry point."""
import argparse
from datetime import datetime
import sys
from .config import AppConfig
from .email_sender import send_report
from .excel_report import write_report
from .mock_p4_client import MockP4Client
from .statistics import calculate_statistics
from .user_loader import load_users


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic Perforce activity report")
    parser.add_argument("--dry-run", action="store_true", help="Generate workbook without sending email")
    parser.add_argument("--send-email", action="store_true", help="Explicitly enable configured SMTP delivery")
    parser.add_argument("--timezone", default="America/Los_Angeles", help="Reporting IANA timezone")
    args = parser.parse_args(argv)
    try:
        config = AppConfig(timezone=args.timezone)
        zone = config.zone()
        now = datetime.now(zone)
        users = load_users(config.userlist)
        changes = MockP4Client(config.mock_data).get_changelists(now)
        stats = calculate_statistics(users, changes, now, zone)
        output = config.reports_dir / f"p4report_{now:%Y-%m-%d}.xlsx"
        write_report(stats, output, args.timezone)
        print(f"Workbook: {output}\nEmployees: {len(users)} | weekly: {stats.weekly_total} | "
              f"monthly: {stats.monthly_total} | yearly: {stats.yearly_total} | unmapped: {len(stats.unmapped)}")
        if args.send_email and not args.dry_run:
            sent = send_report(output, stats)
            print("Email sent." if sent else "Email skipped: SEND_EMAIL is not enabled.")
        else:
            print("Email skipped (dry-run/default behavior).")
        return 0
    except Exception as exc:
        # SMTP and workbook errors can use library-specific exceptions; keep the CLI message concise.
        print(f"p4report failed: {exc}", file=sys.stderr)
        return 1
