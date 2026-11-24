import json
from datetime import UTC, datetime, timedelta

import pytest

from p4report.config import DEFAULT_MOCK_DATA
from p4report.mock_p4_client import MockDataError, MockP4Client
from p4report.p4_client import P4Client

from conftest import LA

AS_OF = datetime(2025, 3, 12, 12, 30, tzinfo=UTC)
WIDE = (datetime(2000, 1, 1, tzinfo=UTC), datetime(2100, 1, 1, tzinfo=UTC))


def rec(**overrides):
    base = {"change": 1, "user": "a", "days_ago": 0, "hour": 9, "description": "x", "files": ["//f"]}
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not ...}


def client(tmp_path, records, as_of=AS_OF):
    path = tmp_path / "data.json"
    path.write_text(records if isinstance(records, str) else json.dumps(records))
    return MockP4Client(path, as_of)


def test_satisfies_protocol(tmp_path):
    assert isinstance(client(tmp_path, []), P4Client)


def test_relative_record_uses_calendar_day_and_hour_in_reference_zone(tmp_path):
    [change] = client(tmp_path, [rec(days_ago=2, hour=7, user="ghost")]).get_changelists(*WIDE)
    assert change.timestamp == datetime(2025, 3, 10, 7, tzinfo=UTC)
    assert change.user == "ghost"
    assert change.files == ("//f",)


def test_relative_record_across_dst_keeps_wall_clock_hour(tmp_path):
    as_of = datetime(2025, 3, 10, 12, tzinfo=LA)  # Monday after spring-forward
    [change] = client(tmp_path, [rec(days_ago=3, hour=9)], as_of).get_changelists(*WIDE)
    assert change.timestamp.astimezone(LA).replace(tzinfo=None) == datetime(2025, 3, 7, 9)
    assert change.timestamp.utcoffset() == timedelta(hours=-8)


def test_absolute_timestamp_record(tmp_path):
    [change] = client(tmp_path, [rec(days_ago=..., hour=..., timestamp="2025-03-10T07:00:00Z")]).get_changelists(*WIDE)
    assert change.timestamp == datetime(2025, 3, 10, 7, tzinfo=UTC)


def test_range_is_half_open_and_future_records_are_not_clamped(tmp_path):
    records = [rec(change=1, days_ago=0, hour=12), rec(change=2, days_ago=0, hour=13),  # 13:00 > as_of 12:30
               rec(change=3, days_ago=1, hour=0)]
    c = client(tmp_path, records)
    got = c.get_changelists(datetime(2025, 3, 11, 0, tzinfo=UTC), AS_OF)
    assert [x.change for x in got] == [1, 3]
    assert [x.change for x in c.get_changelists(datetime(2025, 3, 11, 0, 0, 1, tzinfo=UTC), AS_OF)] == [1]


def test_multiple_changes_same_day_are_independent(tmp_path):
    got = client(tmp_path, [rec(change=1), rec(change=2)]).get_changelists(*WIDE)
    assert [x.change for x in got] == [1, 2]


@pytest.mark.parametrize(("records", "needle"), [
    ("{not json", "invalid JSON"),
    ({"change": 1}, "top level must be a JSON array"),
    (["x"], "record 0: record must be a JSON object"),
    ([rec(days_ago=...)], "record 0: provide exactly one of 'timestamp' or 'days_ago'"),
    ([rec(timestamp="2025-03-10T07:00:00Z")], "provide exactly one"),
    ([rec(user=...)], "record 0: missing required field(s): user"),
    ([rec(), rec(change=2, files=...)], "record 1: missing required field(s): files"),
    ([rec(change=0)], "positive integer"),
    ([rec(change=-5)], "positive integer"),
    ([rec(change="7")], "positive integer"),
    ([rec(change=True)], "positive integer"),
    ([rec(user="  ")], "username must not be empty"),
    ([rec(days_ago=-3)], "'days_ago' must be an integer >= 0"),
    ([rec(days_ago="2")], "'days_ago' must be an integer >= 0"),
    ([rec(hour=24)], "'hour' must be an integer 0-23"),
    ([rec(hour=-1)], "'hour' must be an integer 0-23"),
    ([rec(hour=9.5)], "'hour' must be an integer 0-23"),
    ([rec(days_ago=..., hour=..., timestamp="2025-03-10T07:00:00")], "must include a UTC offset"),
    ([rec(days_ago=..., hour=..., timestamp="yesterday")], "not an ISO-8601 datetime"),
    ([rec(days_ago=..., timestamp="2025-03-10T07:00:00Z")], "'hour' is only valid with 'days_ago'"),
    ([rec(files="//f")], "'files' must be a list of strings"),
    ([rec(description=5)], "description must be a string"),
    ([rec(change=7), rec(change=8), rec(change=7)], "record 2: duplicate changelist number 7 (first seen in record 0)"),
])
def test_invalid_data_reports_file_and_record(tmp_path, records, needle):
    c = client(tmp_path, records)
    with pytest.raises(MockDataError) as info:
        c.get_changelists(*WIDE)
    assert needle in str(info.value)
    assert str(c.data_path) in str(info.value)


def test_naive_reference_time_rejected(tmp_path):
    with pytest.raises(ValueError, match="timezone-aware"):
        MockP4Client(tmp_path / "x.json", datetime(2025, 1, 1))


def test_bundled_demo_data_is_valid_and_unique():
    changes = MockP4Client(DEFAULT_MOCK_DATA, AS_OF).load_all()
    assert len(changes) == 14
    assert len({c.change for c in changes}) == 14
