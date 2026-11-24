"""Calendar and aggregation tests. Expected values are worked out by hand from
the calendar (see comments), not recomputed with the implementation's logic."""
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from p4report.statistics import calculate_statistics, reporting_periods

from conftest import LA, cl, emp

A = emp("Amy", "a")


def counts(stats, username="a"):
    return tuple(next(r.count for r in ps.ranking if r.employee.username == username) for ps in stats.periods)


# --- reporting periods -------------------------------------------------------

def test_monday_scheduled_run_reports_previous_complete_week():
    # Workflow cron: Monday 2026-11-23 17:00 UTC == 09:00 PST.
    as_of = datetime(2026, 11, 23, 17, tzinfo=UTC)
    week, month, year = reporting_periods(as_of, LA)
    assert (week.start, week.end) == (datetime(2026, 11, 16, tzinfo=LA), datetime(2026, 11, 23, tzinfo=LA))
    assert week.end - week.start == timedelta(days=7)
    assert (month.start, month.end) == (datetime(2026, 11, 1, tzinfo=LA), datetime(2026, 11, 23, 9, tzinfo=LA))
    assert (year.start, year.end) == (datetime(2026, 1, 1, tzinfo=LA), datetime(2026, 11, 23, 9, tzinfo=LA))


@pytest.mark.parametrize("day", range(23, 30))
def test_week_is_previous_monday_to_monday_on_every_weekday(day):
    week, _, _ = reporting_periods(datetime(2026, 11, day, 12, tzinfo=LA), LA)
    assert (week.start, week.end) == (datetime(2026, 11, 16, tzinfo=LA), datetime(2026, 11, 23, tzinfo=LA))


def test_week_containing_dst_fall_back_has_169_real_hours():
    week, _, _ = reporting_periods(datetime(2026, 11, 9, 9, tzinfo=LA), LA)  # week of Nov 2 2026 (DST ends Nov 1)
    week_prior, _, _ = reporting_periods(datetime(2026, 11, 2, 9, tzinfo=LA), LA)  # Oct 26 - Nov 2
    assert week.start == datetime(2026, 11, 2, tzinfo=LA)
    assert week_prior.end.astimezone(UTC) - week_prior.start.astimezone(UTC) == timedelta(hours=169)


def test_week_containing_dst_spring_forward_has_167_real_hours():
    week, _, _ = reporting_periods(datetime(2026, 3, 9, 9, tzinfo=LA), LA)  # Mar 2 - Mar 9 2026 (DST starts Mar 8)
    assert week.end.astimezone(UTC) - week.start.astimezone(UTC) == timedelta(hours=167)


def test_naive_as_of_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        reporting_periods(datetime(2026, 1, 1), LA)


# --- boundary membership -----------------------------------------------------

def test_weekly_boundaries_monday_midnight_in_sunday_2359_in_next_monday_out():
    as_of = datetime(2025, 3, 19, 12, tzinfo=LA)  # Wed; previous week = Mon Mar 10 .. Mon Mar 17
    changes = [
        cl(1, "a", datetime(2025, 3, 10, 0, 0, tzinfo=LA)),            # Monday 00:00 -> in
        cl(2, "a", datetime(2025, 3, 16, 23, 59, 59, tzinfo=LA)),      # Sunday 23:59:59 -> in
        cl(3, "a", datetime(2025, 3, 17, 0, 0, tzinfo=LA)),            # next Monday 00:00 -> out
        cl(4, "a", datetime(2025, 3, 9, 23, 59, 59, tzinfo=LA)),       # Sunday before -> out
    ]
    s = calculate_statistics([A], changes, as_of, LA)
    assert s.week.mapped == 2
    assert [r.in_week for r in s.rows] == [False, True, True, False]  # rows sorted by time: 4,1,2,3


def test_month_first_day_in_and_last_day_of_previous_month_out():
    as_of = datetime(2025, 4, 30, 23, 59, tzinfo=LA)
    changes = [cl(1, "a", datetime(2025, 4, 1, tzinfo=LA)), cl(2, "a", datetime(2025, 3, 31, 23, 59, 59, tzinfo=LA)),
               cl(3, "a", datetime(2025, 4, 30, 23, 58, tzinfo=LA))]
    s = calculate_statistics([A], changes, as_of, LA)
    assert (s.month.mapped, s.year.mapped) == (2, 3)


def test_year_first_and_last_day_and_generation_time_is_exclusive():
    as_of = datetime(2025, 12, 31, 23, 59, 59, tzinfo=LA)
    changes = [cl(1, "a", datetime(2025, 1, 1, tzinfo=LA)), cl(2, "a", datetime(2024, 12, 31, 23, 59, 59, tzinfo=LA)),
               cl(3, "a", datetime(2025, 12, 31, 23, 59, 58, tzinfo=LA)), cl(4, "a", as_of)]
    s = calculate_statistics([A], changes, as_of, LA)
    assert counts(s) == (0, 1, 2)  # month: #3 ; year: #1, #3 ; #4 at as_of excluded (end exclusive)


def test_leap_day():
    as_of = datetime(2024, 3, 1, 8, tzinfo=LA)  # Friday; previous week Feb 19 - Feb 26
    changes = [cl(1, "a", datetime(2024, 2, 29, 12, tzinfo=LA)), cl(2, "a", datetime(2024, 3, 1, 0, tzinfo=LA))]
    assert counts(calculate_statistics([A], changes, as_of, LA)) == (0, 1, 2)


def test_previous_week_spanning_new_year():
    as_of = datetime(2026, 1, 5, 9, tzinfo=LA)  # Monday; previous week Dec 29 2025 - Jan 5 2026
    changes = [cl(1, "a", datetime(2025, 12, 29, 0, tzinfo=LA)), cl(2, "a", datetime(2026, 1, 2, tzinfo=LA)),
               cl(3, "a", datetime(2025, 12, 28, 23, tzinfo=LA))]
    assert counts(calculate_statistics([A], changes, as_of, LA)) == (2, 1, 1)


def test_utc_timestamps_are_converted_to_reporting_zone():
    as_of = datetime(2025, 3, 19, 12, tzinfo=LA)
    changes = [cl(1, "a", datetime(2025, 3, 10, 7, 0, tzinfo=UTC)),     # Mon 00:00 PDT -> in
               cl(2, "a", datetime(2025, 3, 10, 6, 59, tzinfo=UTC)),    # Sun 23:59 PDT -> out
               cl(3, "a", datetime(2025, 3, 17, 6, 59, tzinfo=UTC))]    # Sun 23:59 PDT -> in
    s = calculate_statistics([A], changes, as_of, LA)
    assert s.week.mapped == 2
    assert s.rows[0].local_time.utcoffset() == timedelta(hours=-7)


def test_dst_fall_back_ambiguous_hour_compares_real_instants():
    # 2026-11-01 01:30 PDT (fold=0) happened 40 minutes before 01:10 PST (fold=1).
    as_of = datetime(2026, 11, 1, 1, 10, tzinfo=LA, fold=1)
    earlier = datetime(2026, 11, 1, 1, 30, tzinfo=LA, fold=0)
    later = datetime(2026, 11, 1, 1, 20, tzinfo=LA, fold=1)
    s = calculate_statistics([A], [cl(1, "a", earlier), cl(2, "a", later)], as_of, LA)
    assert s.year.mapped == 1
    assert [r.change.change for r in s.rows] == [1, 2]


@pytest.mark.parametrize(("zone", "expected"), [
    # Two instants, as_of Wed 2025-07-09 12:00 UTC; previous week = Mon Jun 30 .. Mon Jul 7 (local).
    #   X = 2025-06-29 23:30 UTC     Y = 2025-06-30 23:30 UTC
    ("UTC", (1, 0, 2)),                  # X Sun Jun 29 (out)       Y Mon Jun 30 (week, June)
    ("America/Los_Angeles", (1, 0, 2)),  # X Sun Jun 29 16:30       Y Mon Jun 30 16:30
    ("Europe/London", (2, 1, 2)),        # X Mon Jun 30 00:30 (week) Y Tue Jul 1 00:30 (week, July)
    ("Asia/Kolkata", (2, 1, 2)),         # X Mon Jun 30 05:00       Y Tue Jul 1 05:00
    ("Asia/Tokyo", (2, 1, 2)),           # X Mon Jun 30 08:30       Y Tue Jul 1 08:30
    ("Pacific/Chatham", (2, 1, 2)),      # X Mon Jun 30 12:15       Y Tue Jul 1 12:15
])
def test_same_instants_bucket_differently_by_reporting_zone(zone, expected):
    changes = [cl(1, "a", datetime(2025, 6, 29, 23, 30, tzinfo=UTC)),
               cl(2, "a", datetime(2025, 6, 30, 23, 30, tzinfo=UTC))]
    s = calculate_statistics([A], changes, datetime(2025, 7, 9, 12, tzinfo=UTC), ZoneInfo(zone))
    assert counts(s) == expected


# --- aggregation, reconciliation, ranking -------------------------------------

def test_mapped_unmapped_totals_reconcile_and_zero_employees_included():
    employees = [emp("Zed", "z"), emp("Amy", "a"), emp("Zero", "zero")]
    as_of = datetime(2025, 1, 8, 12, tzinfo=LA)  # Wed; previous week Dec 30 2024 - Jan 6 2025
    changes = [
        cl(1, "z", datetime(2024, 12, 30, 9, tzinfo=LA)),   # week, year 2024 -> not month/year 2025
        cl(2, "z", datetime(2025, 1, 2, 9, tzinfo=LA)),     # week, month, year
        cl(3, "ghost", datetime(2025, 1, 3, 9, tzinfo=LA)),  # unmapped week, month, year
        cl(4, "a", datetime(2025, 1, 7, 9, tzinfo=LA)),     # month, year (current week)
        cl(5, "GHOST", datetime(2024, 11, 1, tzinfo=LA)),   # unmapped, no period
    ]
    s = calculate_statistics(employees, changes, as_of, LA)
    assert [(ps.mapped, ps.unmapped, ps.total) for ps in s.periods] == [(2, 1, 3), (2, 1, 3), (2, 1, 3)]
    for ps in s.periods:
        assert sum(r.count for r in ps.ranking) == ps.mapped
        assert len(ps.ranking) == 3
    assert [(r.employee.name, r.count) for r in s.week.ranking] == [("Zed", 2), ("Amy", 0), ("Zero", 0)]
    assert s.week.zero_employees == 2
    assert len(s.rows) == 5  # every changelist kept, none duplicated
    [ghost] = s.unmapped_users
    assert (ghost.username, ghost.week, ghost.month, ghost.year, ghost.changes) == ("ghost", 1, 1, 1, (3, 5))


def test_username_matching_is_case_insensitive():
    s = calculate_statistics([emp("Amy", "Amy.Lee")], [cl(1, "amy.lee", datetime(2025, 1, 2, tzinfo=UTC))],
                             datetime(2025, 1, 3, tzinfo=UTC), UTC)
    assert (s.year.mapped, s.year.unmapped) == (1, 0)


def test_duplicate_changelist_from_any_adapter_rejected():
    stamp = datetime(2025, 1, 2, tzinfo=UTC)
    with pytest.raises(ValueError, match="duplicate changelist number 7"):
        calculate_statistics([A], [cl(7, "a", stamp), cl(7, "a", stamp)], datetime(2025, 1, 3, tzinfo=UTC), UTC)


def test_duplicate_employee_username_rejected():
    with pytest.raises(ValueError, match="duplicate Perforce username"):
        calculate_statistics([emp("A", "x"), emp("B", "X", "b@example.com")], [], datetime(2025, 1, 3, tzinfo=UTC), UTC)


def test_naive_changelist_timestamp_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        cl(1, "a", datetime(2025, 1, 2))


def test_competition_ranking_with_alphabetical_ties():
    employees = [emp("bob", "b"), emp("Cara", "c"), emp("Al", "a"), emp("Dee", "d"), emp("eve", "e")]
    stamp = datetime(2025, 1, 2, tzinfo=UTC)
    changes = [cl(i, u, stamp) for i, u in enumerate(["b", "b", "c", "c", "a", "d"], 1)]
    s = calculate_statistics(employees, changes, datetime(2025, 1, 3, tzinfo=UTC), UTC)
    assert [(r.rank, r.employee.name, r.count) for r in s.year.ranking] == [
        (1, "bob", 2), (1, "Cara", 2), (3, "Al", 1), (3, "Dee", 1), (5, "eve", 0)]


def test_rankings_are_independent_per_period():
    employees = [emp("Amy", "a"), emp("Bo", "b")]
    as_of = datetime(2025, 3, 19, 12, tzinfo=UTC)
    changes = [cl(1, "a", datetime(2025, 3, 11, tzinfo=UTC)), cl(2, "b", datetime(2025, 3, 18, tzinfo=UTC)),
               cl(3, "b", datetime(2025, 3, 1, tzinfo=UTC))]
    s = calculate_statistics(employees, changes, as_of, UTC)
    assert [r.employee.name for r in s.week.ranking] == ["Amy", "Bo"]
    assert [r.employee.name for r in s.month.ranking] == ["Bo", "Amy"]


def _oracle(changes, as_of, zone):
    """Independent membership via explicit calendar arithmetic on dates."""
    local_now = as_of.astimezone(zone)
    today = local_now.date()
    out = [0, 0, 0]
    for c in changes:
        local = c.timestamp.astimezone(zone)
        d = local.date()
        monday = today - timedelta(days=today.weekday())
        out[0] += monday - timedelta(days=7) <= d < monday
        before_now = c.timestamp.timestamp() < as_of.timestamp()
        out[1] += (d.year, d.month) == (today.year, today.month) and before_now
        out[2] += d.year == today.year and before_now
    return tuple(out)


@pytest.mark.parametrize("zone", ["America/Los_Angeles", "Europe/London", "Asia/Kolkata", "Pacific/Chatham", "UTC"])
def test_sweep_against_date_based_oracle(zone):
    z = ZoneInfo(zone)
    base = datetime(2024, 1, 1, tzinfo=UTC)
    changes = [cl(i, "a", base + timedelta(minutes=419 * i)) for i in range(1, 1400)]
    for hours in range(0, 24 * 380, 53):
        as_of = base + timedelta(hours=hours)
        assert counts(calculate_statistics([A], changes, as_of, z)) == _oracle(changes, as_of, z), as_of
