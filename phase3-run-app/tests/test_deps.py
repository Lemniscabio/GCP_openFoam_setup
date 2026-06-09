import datetime
from types import SimpleNamespace

from backend.deps import _status_event_to_dict


def test_status_event_to_dict_serializes_proto_plus_datetime():
    event_time = datetime.datetime(2026, 6, 9, 10, 1, tzinfo=datetime.timezone.utc)
    event = SimpleNamespace(
        type_="STATUS_CHANGED",
        description="Job is running",
        event_time=event_time,
    )

    assert _status_event_to_dict(event) == {
        "type": "STATUS_CHANGED",
        "description": "Job is running",
        "event_time": "2026-06-09T10:01:00+00:00",
    }


def test_status_event_to_dict_uses_empty_string_for_unset_event_time():
    event = SimpleNamespace(
        type_="STATUS_CHANGED",
        description="Job status changed",
        event_time=None,
    )

    assert _status_event_to_dict(event)["event_time"] == ""
