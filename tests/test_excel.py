import time
from datetime import UTC, datetime, timedelta

import pytest
from openpyxl import load_workbook

from p4report.excel_report import EXCEL_CELL_LIMIT, safe_text, write_report
from p4report.models import Changelist, Employee
from p4report.statistics import calculate_statistics

from conftest import LA, cl, emp

SHEETS = ["Executive Summary", "Weekly Statistics", "Monthly Statistics", "Yearly Statistics",
          "Changelist Details", "Unmapped Users"]
AS_OF = datetime(2026, 11, 23, 9, tzinfo=LA)  # Monday; previous week Nov 16 - Nov 23


def header_row(ws, first_header):
    return next(c.row for c in ws["A"] if c.value == first_header)


def table(ws, first_header):
    """Rows of the table whose column A header equals ``first_header``, as dicts."""
    h = header_row(ws, first_header)
    headers = [c.value for c in ws[h]]
    return [dict(zip(headers, (c.value for c in row), strict=False))
            for row in ws.iter_rows(min_row=h + 1) if row[0].value is not None]


@pytest.fixture
def workbook(tmp_path):
    employees = [emp("Zed", "z"), emp("Amy", "a"), emp("Zero", "zero")]
    changes = [
        cl(1, "z", datetime(2026, 11, 16, 0, tzinfo=LA), "week start", ("//a", "//b")),
        cl(2, "a", datetime(2026, 11, 22, 23, 59, tzinfo=LA)),
        cl(3, "z", datetime(2026, 11, 20, 16, tzinfo=UTC)),          # Fri 08:00 PST
        cl(4, "ghost", datetime(2026, 11, 18, tzinfo=LA)),
        cl(5, "a", datetime(2026, 11, 23, 8, tzinfo=LA)),             # current week -> month/year only
        cl(6, "z", datetime(2026, 2, 1, tzinfo=LA)),
        cl(7, "ghost", datetime(2025, 12, 31, tzinfo=LA)),            # outside every period
    ]
    stats = calculate_statistics(employees, changes, AS_OF, LA)
    path = write_report(stats, tmp_path / "r.xlsx")
    wb = load_workbook(path)
    yield wb
    wb.close()


def test_six_sheets_in_order(workbook):
    assert workbook.sheetnames == SHEETS


def test_statistics_sheets_counts_ranks_and_reconciliation(workbook):
    # Hand count: week z=2 (#1,#3) a=1 (#2); month adds a #5; year adds z #6.
    expected = {"Weekly": [(1, "Zed", 2), (2, "Amy", 1), (3, "Zero", 0)],
                "Monthly": [(1, "Amy", 2), (1, "Zed", 2), (3, "Zero", 0)],
                "Yearly": [(1, "Zed", 3), (2, "Amy", 2), (3, "Zero", 0)]}
    summary = {r["Period"]: r for r in table(workbook["Executive Summary"], "Period")}
    for title, rows in expected.items():
        ws = workbook[f"{title} Statistics"]
        got = [(r["Rank"], r["Employee Name"], r["Changelist Count"]) for r in table(ws, "Rank")]
        assert got == rows
        assert sum(r[2] for r in got) == summary[title]["Mapped Changelists"]
    assert [(summary[t]["Mapped Changelists"], summary[t]["Unmapped Changelists"], summary[t]["Total Changelists"])
            for t in ("Weekly", "Monthly", "Yearly")] == [(3, 1, 4), (4, 1, 5), (5, 1, 6)]


def test_period_labels_on_statistics_sheets(workbook):
    ws = workbook["Weekly Statistics"]
    labels = {ws.cell(r, 1).value: ws.cell(r, 2).value for r in range(1, 7)}
    assert labels["Start (inclusive)"] == datetime(2026, 11, 16, 0, 0)
    assert labels["End (exclusive)"] == datetime(2026, 11, 23, 0, 0)
    assert labels["Timezone"] == "America/Los_Angeles"
    assert "Competition ranking" in labels["Ranking policy"]
    monthly = workbook["Monthly Statistics"]
    assert monthly["B2"].value == datetime(2026, 11, 1) and monthly["B3"].value == datetime(2026, 11, 23, 9)
    summary_text = " ".join(str(c.value) for c in workbook["Executive Summary"]["B"] if c.value)
    assert "2026-11-16 00:00:00 PST to 2026-11-23 00:00:00 PST (end exclusive)" in summary_text
    assert "end is exclusive" in summary_text


def test_changelist_details_all_rows_local_datetimes_and_flags(workbook):
    rows = table(workbook["Changelist Details"], "Changelist Number")
    assert [r["Changelist Number"] for r in rows] == [7, 6, 1, 4, 3, 2, 5]
    by_id = {r["Changelist Number"]: r for r in rows}
    three = by_id[3]
    assert three["Submitted (America/Los_Angeles)"] == datetime(2026, 11, 20, 8, 0)
    assert three["UTC Offset"] == "UTC-08:00"
    assert (three["In Week"], three["In Month"], three["In Year"]) == ("Yes", "Yes", "Yes")
    assert (by_id[5]["In Week"], by_id[5]["In Month"]) == ("No", "Yes")
    assert (by_id[7]["Mapped"], by_id[7]["Employee Name"], by_id[7]["In Year"]) == ("No", None, "No")
    assert by_id[1]["Files"] == "//a\n//b"
    ws = workbook["Changelist Details"]
    assert ws["E2"].number_format == "yyyy-mm-dd hh:mm:ss"
    assert ws["E2"].is_date


def test_unmapped_users_summary(workbook):
    [ghost] = table(workbook["Unmapped Users"], "Perforce Username")
    assert ghost == {"Perforce Username": "ghost", "Weekly Changelists": 1, "Monthly Changelists": 1,
                     "Yearly Changelists": 1, "Changelist Numbers": "4, 7"}


def test_formatting(workbook):
    for name in SHEETS[1:]:
        ws = workbook[name]
        first = "Rank" if "Statistics" in name else ws["A1"].value
        h = header_row(ws, first)
        assert ws.freeze_panes == f"A{h + 1}"
        assert ws.auto_filter.ref.startswith(f"A{h}:")
        head = ws.cell(h, 1)
        assert head.font.b and head.fill.fgColor.rgb == "001F4E78"
        if ws.max_row >= h + 2:
            assert ws.cell(h + 2, 1).fill.fgColor.rgb == "00EAF2F8"  # banding on alternate rows
            assert ws.cell(h + 1, 1).fill.fgColor.rgb != "00EAF2F8"
        assert all((ws.column_dimensions[c].width or 0) >= 10 for c in "ABCDE")
    stats = workbook["Weekly Statistics"]
    assert stats.cell(header_row(stats, "Rank") + 1, 5).number_format == "0"


def test_empty_report_is_valid(tmp_path):
    stats = calculate_statistics([emp("Amy", "a")], [], AS_OF, LA)
    wb = load_workbook(write_report(stats, tmp_path / "e.xlsx"))
    assert wb.sheetnames == SHEETS
    assert table(wb["Changelist Details"], "Changelist Number") == []
    assert wb["Unmapped Users"].auto_filter.ref == "A1:E1"


DANGEROUS = ["=1+1", "+1+1", "-1+1", "@SUM(A1)", "\t=1+1", "\r=1+1",
             '=HYPERLINK("http://evil.example","x")']


@pytest.mark.parametrize("payload", DANGEROUS)
def test_formula_injection_neutralised_in_every_text_column(tmp_path, payload):
    # Email and username fields are validated, so their formula vectors come from
    # their allowed characters; names, descriptions, files and unknown users are free text.
    employee = Employee(payload, "=x@example.com" if payload.startswith("=") else "a@example.com",
                        "-u" if payload.startswith("-") else "a")
    stamp = datetime(2026, 11, 18, tzinfo=LA)
    changes = [Changelist(1, employee.username, stamp, payload, (payload, "//ok")),
               Changelist(2, payload.strip() or "x", stamp, payload, (payload,))]
    stats = calculate_statistics([employee], changes, AS_OF, LA)
    wb = load_workbook(write_report(stats, tmp_path / "i.xlsx"))
    def norm(text):  # XML parsing normalises CR to LF on read-back
        return text.replace("\r\n", "\n").replace("\r", "\n")

    targets = {norm(payload), norm(payload + "\n//ok")}
    checked = 0
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                assert cell.data_type != "f", f"{ws.title}!{cell.coordinate} is a live formula"
                if isinstance(cell.value, str) and norm(cell.value[1:]) in targets:
                    assert cell.value.startswith("'")
                    checked += 1
    assert checked >= 6  # name x3 sheets, description x2, files x2, unknown user


def test_illegal_control_characters_are_replaced_not_fatal(tmp_path):
    stamp = datetime(2026, 11, 18, tzinfo=LA)
    stats = calculate_statistics([emp("Amy\x07", "a")], [cl(1, "a", stamp, "bad\x00desc\x1b", ("//f\x0b",))],
                                 AS_OF, LA)
    wb = load_workbook(write_report(stats, tmp_path / "c.xlsx"))
    [row] = table(wb["Changelist Details"], "Changelist Number")
    assert row["Description"] == "bad�desc�"
    assert row["Files"] == "//f�"
    assert row["Employee Name"] == "Amy�"


def test_safe_text_unit():
    assert safe_text("normal //depot/x") == "normal //depot/x"
    assert safe_text("=cmd") == "'=cmd"
    assert safe_text("a" * 40000) == "a" * EXCEL_CELL_LIMIT


def test_large_dataset_is_linear_enough(tmp_path):
    employees = [emp(f"E{i:03}", f"u{i}") for i in range(300)]
    changes = [cl(i, f"u{i % 350}", AS_OF - timedelta(hours=1 + i % 7000)) for i in range(1, 20001)]
    stats = calculate_statistics(employees, changes, AS_OF, LA)
    started = time.perf_counter()
    path = write_report(stats, tmp_path / "big.xlsx")
    elapsed = time.perf_counter() - started
    assert elapsed < 30, f"20k rows took {elapsed:.1f}s"
    wb = load_workbook(path, read_only=True)
    assert wb["Changelist Details"].max_row == 20001
    wb.close()
