# p4report

`p4report` is a public portfolio demonstration that rebuilds a weekly Perforce changelist report using synthetic data. It loads an employee directory and changelists from local files, calculates weekly, monthly, and yearly counts in memory, creates a formatted Excel workbook, and can optionally deliver that workbook through SMTP. It needs no database and makes no Perforce or other network calls during report generation.

The original business use case was a Python job that read an engineering directory and Perforce activity, ranked weekly activity, wrote an Excel report, and emailed it to an engineering manager. This project demonstrates the workflow without proprietary code, real employees, company details, or server access. Every person, email address, username, changelist, description, and path in `data/` is synthetic placeholder data. Counts describe activity only and are not performance scores.

## Architecture and structure

The flow is employee file → `P4Client` abstraction → local `MockP4Client` → calendar aggregation → Excel workbook → optional SMTP delivery. A future private deployment can implement the `P4Client` protocol against its approved Perforce API and inject it into the reporting flow; this public project intentionally contains no real Perforce implementation.

```text
.github/workflows/weekly-report.yml
data/userlist.txt              synthetic employee directory
data/mock_p4_data.json         relative-date synthetic changelists
reports/.gitkeep              generated workbooks are ignored by Git
src/p4report/                  CLI, models, adapter, statistics, Excel, email
tests/                         unit tests
```

## Install and run locally

Python 3.12 or newer is required.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m p4report
```

The default command writes `reports/p4report_YYYY-MM-DD.xlsx`, prints totals, and skips email. These equivalent modes are also available:

```bash
python -m p4report --dry-run
python -m p4report --timezone America/Los_Angeles
python -m p4report --send-email
```

`--dry-run` always suppresses delivery. `--send-email` only requests delivery; the `SEND_EMAIL` environment variable must also be explicitly set to `true`. The filename date follows the configured reporting timezone. Week boundaries are Monday 00:00 through Sunday 23:59:59.999999, and month/year counts use calendar boundaries.

## SMTP delivery

Configure all of these environment variables in a secure environment; do not commit credentials or `.env` files:

```bash
export SEND_EMAIL=true
export SMTP_HOST=smtp.example.net
export SMTP_PORT=587
export SMTP_USERNAME='your-smtp-user'
export SMTP_PASSWORD='your-smtp-password'
export SMTP_FROM=reports@example.net
export REPORT_RECIPIENT=manager@example.net
python -m p4report --send-email
```

The sender uses STARTTLS. If email is opted in but SMTP configuration is incomplete or delivery fails, the command exits nonzero and reports the failure; it does not claim delivery. `REPORT_RECIPIENT` defaults to `aaa@example.com`, a placeholder that is not a real delivery address. Never use this default for actual delivery.

## GitHub Actions

`.github/workflows/weekly-report.yml` runs on Ubuntu, installs Python 3.12 and dependencies, generates the workbook, then uploads it as an artifact even when delivery fails. The schedule is Monday at 17:00 UTC. GitHub cron is UTC: this is 9:00 AM Pacific during standard time and 10:00 AM during daylight time.

For scheduled email, add repository **Actions secrets** named `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_FROM`. Add repository variable `SEND_EMAIL` with value `true` to explicitly enable scheduled delivery; it is unset by default, so scheduled jobs remain dry-run. Optionally add `REPORT_RECIPIENT` as a repository variable. Manual workflow runs offer a `send_email` checkbox, default false; secrets must still be configured. The artifact named `p4report-<run id>` is available on the workflow run page under **Artifacts**. The workflow does not commit reports to the repository.

## Tests

```bash
python -m pytest
```

Tests use fixed injected datetimes, temporary output paths, and mocked SMTP. No real email is sent.
