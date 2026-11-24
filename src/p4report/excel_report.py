"""Create a formatted six-sheet Excel report."""
from datetime import datetime
from pathlib import Path
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from .statistics import ReportStats

HEADERS = ["Rank", "Employee Name", "Email", "Perforce Username", "Changelist Count"]


def _format_table(ws, widths: list[int]) -> None:
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for index, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(index)].width = width
    for row in range(2, ws.max_row + 1):
        if row % 2 == 0:
            for cell in ws[row]:
                cell.fill = PatternFill("solid", fgColor="EAF2F8")


def _statistics_sheet(wb: Workbook, title: str, rows) -> None:
    ws = wb.create_sheet(title)
    ws.append(HEADERS)
    for rank, item in enumerate(rows, 1):
        e = item.employee
        ws.append([rank, e.name, e.email, e.username, item.count])
    _format_table(ws, [10, 26, 32, 24, 20])
    for cell in ws["E"][1:]:
        cell.number_format = "0"


def write_report(stats: ReportStats, output_path: Path, timezone: str) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    summary = wb.active
    summary.title = "Executive Summary"
    summary.append(["Metric", "Value"])
    values = [
        ("Report generated", stats.generated_at.strftime("%Y-%m-%d %H:%M:%S %Z")),
        ("Reporting timezone", timezone),
        ("Reporting period", f"{stats.period_start:%Y-%m-%d %H:%M} to {stats.period_end:%Y-%m-%d %H:%M}"),
        ("Total employees", len(stats.weekly)),
        ("Weekly changelists", stats.weekly_total),
        ("Monthly changelists", stats.monthly_total),
        ("Yearly changelists", stats.yearly_total),
        ("Employees with zero weekly changelists", stats.zero_weekly),
        ("Unmapped changelists", len(stats.unmapped)),
    ]
    for value in values:
        summary.append(value)
    _format_table(summary, [42, 62])
    for row in range(2, summary.max_row + 1):
        summary.cell(row, 1).font = Font(bold=True)
        summary.cell(row, 2).fill = PatternFill("solid", fgColor="D9EAD3")
    _statistics_sheet(wb, "Weekly Statistics", stats.weekly)
    _statistics_sheet(wb, "Monthly Statistics", stats.monthly)
    _statistics_sheet(wb, "Yearly Statistics", stats.yearly)
    details = wb.create_sheet("Changelist Details")
    details.append(["Changelist Number", "Perforce Username", "Employee Name", "Submission Timestamp", "Description", "Files"])
    for change, employee in stats.mapped:
        details.append([change.change, change.user, employee.name, change.timestamp.isoformat(), change.description, "\n".join(change.files)])
    _format_table(details, [19, 23, 25, 34, 48, 56])
    details.freeze_panes = "A2"
    unmapped = wb.create_sheet("Unmapped Users")
    unmapped.append(["Changelist Number", "Perforce Username", "Submission Timestamp", "Description", "Files"])
    for change in stats.unmapped:
        unmapped.append([change.change, change.user, change.timestamp.isoformat(), change.description, "\n".join(change.files)])
    _format_table(unmapped, [19, 23, 34, 48, 56])
    wb.save(output_path)
    # Reopen to catch malformed output before reporting success.
    load_workbook(output_path, read_only=True).close()
    return output_path
