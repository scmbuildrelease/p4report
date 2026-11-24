"""Create the formatted six-sheet Excel report."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from .statistics import Period, PeriodStats, ReportStats

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
EXCEL_CELL_LIMIT = 32767
DATETIME_FORMAT = "yyyy-mm-dd hh:mm:ss"
BOUNDARY_NOTE = "Start is inclusive; end is exclusive. Boundaries use the reporting timezone."
RANKING_NOTE = ("Competition ranking: count descending, ties share a rank and the next rank is skipped "
                "(1, 1, 3); tied employees are listed alphabetically by name.")
STAT_HEADERS = ["Rank", "Employee Name", "Email", "Perforce Username", "Changelist Count"]
HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
BAND_FILL = PatternFill("solid", fgColor="EAF2F8")
LABEL_FONT = Font(bold=True)


def safe_text(value: str) -> str:
    """Make untrusted text inert in Excel: strip illegal XML characters,
    neutralise formula prefixes with a leading apostrophe and respect the
    per-cell length limit."""
    text = ILLEGAL_CHARACTERS_RE.sub("�", value)
    if text.startswith(FORMULA_PREFIXES):
        text = "'" + text
    return text[:EXCEL_CELL_LIMIT]


def _cells(values: Iterable[Any]) -> list[Any]:
    return [safe_text(v) if isinstance(v, str) else v for v in values]


def _local(stamp: datetime) -> datetime:
    """Excel cannot store offsets; write the reporting-zone wall time."""
    return stamp.replace(tzinfo=None)


def _offset(stamp: datetime) -> str:
    raw = stamp.strftime("%z")
    return f"UTC{raw[:3]}:{raw[3:]}"


def _table(ws: Worksheet, header_row: int, headers: Sequence[str], rows: Iterable[Sequence[Any]],
           widths: Sequence[int], formats: dict[int, str] | None = None, freeze: bool = True) -> None:
    """Write a banded, filterable table whose header is on ``header_row``."""
    for col, title in enumerate(headers, 1):
        cell = ws.cell(header_row, col, title)
        cell.font, cell.fill = HEADER_FONT, HEADER_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    last = header_row
    for last, values in enumerate(rows, header_row + 1):
        for col, value in enumerate(_cells(values), 1):
            cell = ws.cell(last, col, value)
            if formats and col in formats:
                cell.number_format = formats[col]
            if (last - header_row) % 2 == 0:
                cell.fill = BAND_FILL
    if freeze:
        ws.freeze_panes = ws.cell(header_row + 1, 1).coordinate
    ws.auto_filter.ref = f"A{header_row}:{get_column_letter(len(headers))}{last}"
    for col, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(col)].width = width


def _label_rows(ws: Worksheet, pairs: Iterable[tuple[str, Any]], start_row: int = 1) -> int:
    row = start_row
    for row, (label, value) in enumerate(pairs, start_row):
        ws.cell(row, 1, label).font = LABEL_FONT
        cell = ws.cell(row, 2, safe_text(value) if isinstance(value, str) else value)
        if isinstance(value, datetime):
            cell.number_format = DATETIME_FORMAT
    return row


def _period_text(period: Period) -> str:
    return f"{period.start:%Y-%m-%d %H:%M:%S %Z} to {period.end:%Y-%m-%d %H:%M:%S %Z} (end exclusive)"


def _summary(ws: Worksheet, stats: ReportStats) -> None:
    ws.title = "Executive Summary"
    pairs: list[tuple[str, Any]] = [
        ("Report generated", f"{stats.generated_at:%Y-%m-%d %H:%M:%S %Z}"),
        ("Reporting timezone", stats.timezone_name),
        ("Total employees", stats.employee_count),
    ]
    for ps in stats.periods:
        pairs.append((f"{ps.period.title} period", _period_text(ps.period)))
    pairs += [("Boundary policy", BOUNDARY_NOTE), ("Ranking policy", RANKING_NOTE),
              ("Data", "Synthetic demonstration data; counts describe activity, not performance.")]
    last = _label_rows(ws, pairs)
    _table(ws, last + 2, ["Period", "Mapped Changelists", "Unmapped Changelists", "Total Changelists",
                          "Employees With Zero"],
           [[ps.period.title, ps.mapped, ps.unmapped, ps.total, ps.zero_employees] for ps in stats.periods],
           [34, 92, 22, 20, 22], freeze=False)
    for row in ws.iter_rows(min_row=1, max_row=last):
        row[1].alignment = Alignment(wrap_text=True, vertical="top")


def _statistics_sheet(wb: Workbook, ps: PeriodStats, timezone_name: str) -> None:
    ws = wb.create_sheet(f"{ps.period.title} Statistics")
    last = _label_rows(ws, [
        ("Period", ps.period.description),
        ("Start (inclusive)", _local(ps.period.start)),
        ("End (exclusive)", _local(ps.period.end)),
        ("Timezone", timezone_name),
        ("Mapped changelists", ps.mapped),
        ("Ranking policy", RANKING_NOTE),
    ])
    rows = [[r.rank, r.employee.name, r.employee.email, r.employee.username, r.count] for r in ps.ranking]
    _table(ws, last + 2, STAT_HEADERS, rows, [22, 30, 32, 24, 20], {1: "0", 5: "0"})


def _details_sheet(wb: Workbook, stats: ReportStats) -> None:
    ws = wb.create_sheet("Changelist Details")
    headers = ["Changelist Number", "Perforce Username", "Employee Name", "Mapped",
               f"Submitted ({stats.timezone_name})", "UTC Offset", "In Week", "In Month", "In Year",
               "Description", "Files"]
    yes = {True: "Yes", False: "No"}
    rows = [[r.change.change, r.change.user, r.employee.name if r.employee else "", yes[r.employee is not None],
             _local(r.local_time), _offset(r.local_time), yes[r.in_week], yes[r.in_month], yes[r.in_year],
             r.change.description, "\n".join(r.change.files)] for r in stats.rows]
    _table(ws, 1, headers, rows, [19, 22, 24, 10, 26, 12, 10, 10, 10, 48, 56], {1: "0", 5: DATETIME_FORMAT})


def _unmapped_sheet(wb: Workbook, stats: ReportStats) -> None:
    ws = wb.create_sheet("Unmapped Users")
    rows = [[u.username, u.week, u.month, u.year, ", ".join(map(str, u.changes))] for u in stats.unmapped_users]
    _table(ws, 1, ["Perforce Username", "Weekly Changelists", "Monthly Changelists", "Yearly Changelists",
                   "Changelist Numbers"], rows, [26, 20, 20, 20, 48], {2: "0", 3: "0", 4: "0"})


def write_report(stats: ReportStats, output_path: Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    summary = wb.active
    if summary is None:  # pragma: no cover - a new Workbook always has one sheet
        raise RuntimeError("openpyxl created a workbook without a worksheet")
    _summary(summary, stats)
    for ps in stats.periods:
        _statistics_sheet(wb, ps, stats.timezone_name)
    _details_sheet(wb, stats)
    _unmapped_sheet(wb, stats)
    wb.save(output_path)
    # Reopen to catch malformed output before reporting success.
    load_workbook(output_path, read_only=True).close()
    return output_path
