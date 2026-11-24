# p4report

`p4report` is a public portfolio demonstration that rebuilds a weekly Perforce changelist report using synthetic data. It loads an employee directory and changelists from local files, calculates weekly, monthly and yearly counts in memory, writes a formatted Excel workbook, and can optionally deliver it over SMTP. It needs no database and makes no Perforce or other network calls while generating the report.

The original business use case was a Python job that read an engineering directory and Perforce activity, ranked weekly activity, wrote an Excel report and emailed it to an engineering manager. This project demonstrates that workflow without proprietary code, real employees, company details or server access. Every person, email address, username, changelist, description and path in the bundled data is synthetic. Counts describe activity only and are not performance scores.

## Architecture

```text
userlist.txt ──► user_loader ─┐
                              ├─► statistics ──► excel_report ──► (optional) email_sender
P4Client.get_changelists ─────┘   (periods,        (6 sheets)        (STARTTLS / SMTPS,
  └─ MockP4Client (JSON)           ranking)                           verified TLS)
```

```text
.github/workflows/weekly-report.yml   CI (ruff, mypy, pytest) + scheduled report job
src/p4report/data/userlist.txt        synthetic employee directory (bundled package data)
src/p4report/data/mock_p4_data.json   synthetic changelists (bundled package data)
src/p4report/                         CLI, models, adapter protocol, statistics, Excel, email
tests/                                unit, integration, workflow and packaging tests
reports/                              default output directory (generated files are git-ignored)
```

`P4Client` (in `p4_client.py`) is the only data-source contract: `get_changelists(start, end)` returns changelists with `start <= timestamp < end` and timezone-aware timestamps. A private deployment can implement it against an approved Perforce API and pass a factory to `p4report.cli.main(client_factory=...)` without changing the statistics, Excel or email code. This public project intentionally contains no real Perforce client.

## Install and run

Python 3.12 or newer is required.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt   # runtime dependencies only
python -m pip install .                     # or: pip install -e . for development
python -m p4report                          # or the `p4report` console script
```

The demo inputs ship inside the package, so the command works from any directory. The workbook is written to `./reports/p4report_YYYY-MM-DD.xlsx` (date in the reporting timezone).

| Option | Meaning |
|---|---|
| `--userlist PATH` | Employee directory (default: bundled demo file). Relative paths are resolved against the current directory. |
| `--data PATH` | Mock Perforce JSON (default: bundled demo file). |
| `--output-dir DIR` | Output directory (default: `reports`, relative to the current directory). |
| `--timezone NAME` | IANA reporting timezone (default `America/Los_Angeles`). |
| `--as-of DATETIME` | Reference time in ISO-8601; without an offset it is read in the reporting timezone. Default: now. |
| `--dry-run` | Never send email, even when `--send-email` is also given. |
| `--send-email` | Request delivery. Email is only sent if `SEND_EMAIL=true` is **also** set. |

Without `--send-email`, or with `--dry-run`, no email is ever sent. Exit codes: `0` success (including skipped email), `1` report generation or email delivery failure, `2` invalid command-line usage. The workbook is always written before any email attempt, so it exists even when delivery fails.

## Reporting policy

All boundaries are midnight in the reporting timezone. Intervals are half-open: the start is included and the end is excluded. Comparisons use absolute UTC instants, so daylight-saving transitions cannot reorder events.

| Period | Start (inclusive) | End (exclusive) |
|---|---|---|
| Weekly | Monday 00:00 of the **previous complete week** | Monday 00:00 of the current week |
| Monthly | 1st of the current month, 00:00 | report generation time |
| Yearly | January 1 of the current year, 00:00 | report generation time |

For example, the scheduled run on Monday 2026-11-23 reports the week from 2026-11-16 00:00 up to 2026-11-23 00:00. The periods overlap by design: one changelist can count in the weekly, monthly and yearly totals, but never twice within one period. Duplicate changelist numbers are rejected.

- **Mapped and unmapped.** A changelist is *mapped* when its Perforce username matches an employee. Usernames are compared case-insensitively. For every period, the employee rows add up to the mapped count, and `mapped + unmapped = total`. Unmapped changelists are never dropped: they are counted separately and listed per username.
- **Ranking.** Changelist count descending; ties broken alphabetically by employee name (case-insensitive). Ranks use *competition ranking*: tied employees share a rank and the next rank is skipped (1, 1, 3). Employees with zero changelists are listed at the bottom.

## Input formats

`userlist.txt`: one `name|email|p4_username` per line. Blank lines and `#` comments are ignored, and a UTF-8 byte-order mark is accepted. Usernames and email addresses must be unique (case-insensitive). Duplicate display names are allowed because two people can share a name; they are distinguished by email and username. An empty directory is rejected. Errors name the file and line.

`mock_p4_data.json`: an array of objects with `change` (positive integer, unique), `user`, `description`, `files` (list of strings), and either:

- `timestamp`: ISO-8601 with a UTC offset, or
- `days_ago` (integer ≥ 0) with an optional `hour` (0–23, default 12). The record is placed that many calendar days before the reference time, at that hour in the reporting timezone.

Relative records keep the demo populated on any run date. Errors name the file and record index.

## Workbook

1. **Executive Summary**: generation time, timezone, every period's boundaries, the boundary and ranking policies, and a table of mapped / unmapped / total changelists and zero-activity employees per period.
2. **Weekly, Monthly and Yearly Statistics**: a period header (start, exclusive end, timezone, ranking policy) above a ranked table of every employee.
3. **Changelist Details**: every fetched changelist with its employee (or blank), submission time as an Excel datetime in the reporting timezone plus its UTC offset, and In Week / In Month / In Year flags.
4. **Unmapped Users**: per unknown username, its weekly, monthly and yearly counts and changelist numbers.

All text from inputs is written as inert text. Values starting with `=`, `+`, `-`, `@`, tab or carriage return are prefixed with `'` so spreadsheet software cannot treat them as formulas. Characters Excel cannot store are replaced with `U+FFFD`.

## SMTP delivery

Configure these in a secure environment (never commit credentials or `.env` files):

```bash
export SEND_EMAIL=true
export SMTP_HOST=smtp.your-provider.net
export SMTP_PORT=587               # STARTTLS; 465 uses implicit TLS (SMTPS)
export SMTP_USERNAME='your-smtp-user'
export SMTP_PASSWORD='your-smtp-password'
export SMTP_FROM=reports@your-domain.net
export REPORT_RECIPIENT=manager@your-domain.net
python -m p4report --send-email
```

TLS always verifies the server certificate and hostname. `REPORT_RECIPIENT` is required for delivery. Reserved placeholder domains (`example.com`, `example.org`, `example.net` and their subdomains, plus the `.example`, `.test`, `.invalid` and `.localhost` TLDs) are refused before any connection is made. The demonstration placeholder `aaa@example.com` can therefore never receive the report.

Missing or invalid settings, connection, authentication, delivery and refused-recipient errors all exit `1`. The command never prints "Email sent." unless the SMTP server accepted the message. The password is never printed.

## GitHub Actions

`.github/workflows/weekly-report.yml` has two jobs. Third-party actions are pinned to full commit SHAs (checkout v7.0.1, setup-python v7.1.0, upload-artifact v7.0.2). The token is limited to `contents: read`.

- **test** runs on every push to `main`, pull request, schedule and manual run. It installs `requirements-dev.txt` and runs Ruff, mypy and pytest on Python 3.12.
- **report** runs only on the schedule or a manual dispatch, and only after **test** passes. It installs runtime dependencies only, generates the workbook, and uploads `reports/*.xlsx` as the artifact `p4report-<run id>` (kept 30 days). The upload step uses `if: always()`, so the workbook is preserved even when email delivery fails. Reports are never committed back to the repository.

The schedule is Monday 17:00 UTC (GitHub cron is always UTC): 09:00 Pacific during standard time and 10:00 during daylight time. Concurrent CI runs for the same ref are cancelled; report runs are never cancelled mid-flight.

**Email is off by default.**

- Scheduled runs send only if the repository **variable** `SEND_EMAIL` is `true`.
- Manual runs send only if the `send_email` checkbox is ticked.
- Either way you also need the **secrets** `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` and `SMTP_FROM`, and the **variable** `REPORT_RECIPIENT`.

## Development

```bash
python -m pip install -r requirements-dev.txt && python -m pip install --no-deps -e .
ruff check .
mypy
python -m pytest            # coverage gate: 95%
```

Tests use fixed reference datetimes, temporary output directories and a fake SMTP class. No real email is sent and no network is used.
