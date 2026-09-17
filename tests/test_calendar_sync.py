from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from sync_aisnet import parse_aisnet_events
from sync_timeedit import parse_timeedit_events
from sync_utils import BERLIN, FeedValidationError, publish_calendar, reconcile_events
from update_calendar import expand_events, generate_ical

NOW = datetime(2026, 1, 1, 12, tzinfo=BERLIN)


def event(source: str | None, uid: str | None, title: str, start: str, end: str):
    result = {"title": title, "start": start, "end": end}
    if source:
        result["source"] = source
    if uid:
        result["source_uid"] = uid
    return result


@pytest.mark.parametrize("source", ["timeedit", "aisnet"])
def test_reconciliation_preserves_updates_and_adds(source, caplog):
    historical = event(source, "old", "Old", "2024-01-01 09:00", "2024-01-01 10:00")
    changing = event(source, "same", "Before", "2026-04-01 09:00", "2026-04-01 10:00")
    missing = event(source, "missing", "Maybe cancelled", "2026-05-01 09:00", "2026-05-01 10:00")
    manual = event(None, None, "Manual", "2026-06-01 09:00", "2026-06-01 10:00")
    other = event("other", "x", "Other", "2026-06-02 09:00", "2026-06-02 10:00")
    updated = event(source, "same", "After", "2026-04-01 11:00", "2026-04-01 12:00")
    new = event(source, "new", "New", "2026-07-01 09:00", "2026-07-01 10:00")

    result = reconcile_events(
        [historical, changing, missing, manual, other], [updated, new], source, now=NOW
    )

    assert historical in result
    assert changing not in result and updated in result
    assert missing in result and "Retaining future" in caplog.text
    assert manual in result and other in result and new in result
    assert reconcile_events(result, [updated, new], source, now=NOW) == result


def test_generated_ics_preserves_history_and_uid_through_metadata_change():
    old = event("timeedit", "stable-1", "Old title", "2024-01-01 09:00", "2024-01-01 10:00")
    changed = event("timeedit", "stable-1", "New title", "2024-01-01 11:00", "2024-01-01 12:00")
    before = generate_ical(expand_events([old]))
    after = generate_ical(expand_events([changed]))
    assert "UID:timeedit-stable-1@fs-ise" in before
    assert "UID:timeedit-stable-1@fs-ise" in after
    assert "SUMMARY:New title" in after


def test_publish_writes_reconciled_yaml_and_ics(tmp_path):
    historical = event("aisnet", "history", "History", "2024-01-01 09:00", "2024-01-01 10:00")
    yaml_path = tmp_path / "events.yaml"
    ics_path = tmp_path / "calendar.ical"
    publish_calendar([historical], events_path=yaml_path, ical_path=ics_path)
    assert yaml.safe_load(yaml_path.read_text()) == [historical]
    assert "UID:aisnet-history@fs-ise" in ics_path.read_text()


@pytest.mark.parametrize(
    ("parser", "payload"),
    [(parse_timeedit_events, b""), (parse_timeedit_events, b"not ical"),
     (parse_aisnet_events, ""), (parse_aisnet_events, "not ical")],
)
def test_empty_or_malformed_feeds_are_rejected(parser, payload):
    with pytest.raises(FeedValidationError):
        parser(payload)


def test_timeedit_parses_fixture_and_rejects_duplicate_uid():
    fixture = b"""BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
UID:te-1\r
DTSTART:20260401T090000\r
DTEND:20260401T100000\r
SUMMARY:Lecture\r
LOCATION:Room 1\r
END:VEVENT\r
END:VCALENDAR\r
"""
    parsed = parse_timeedit_events(fixture)
    assert parsed[0]["source_uid"] == "te-1"
    with pytest.raises(FeedValidationError, match="duplicate UID"):
        reconcile_events([], parsed + parsed, "timeedit", now=NOW)


def test_aisnet_parses_fixture_and_rejects_conflicting_uid():
    fixture = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:ais-1
DTSTART;VALUE=DATE:20260614
DTEND;VALUE=DATE:20260617
SUMMARY:ECIS 2026
LOCATION:Europe
END:VEVENT
END:VCALENDAR
"""
    parsed = parse_aisnet_events(fixture)
    assert parsed[0]["source_uid"]
    conflicting = {**parsed[0], "title": "ICIS instead"}
    with pytest.raises(FeedValidationError, match="conflicting UID"):
        reconcile_events([], [parsed[0], conflicting], "aisnet", now=NOW)


def test_missing_essential_information_is_rejected():
    incomplete = event("timeedit", "x", "", "2026-01-02 09:00", "2026-01-02 10:00")
    with pytest.raises(FeedValidationError, match="title"):
        reconcile_events([], [incomplete], "timeedit", now=NOW)


def test_suspicious_future_reduction_but_not_rolling_shift():
    existing = [
        event("timeedit", str(i), f"Event {i}", f"2026-02-{i + 1:02} 09:00", f"2026-02-{i + 1:02} 10:00")
        for i in range(8)
    ]
    with pytest.raises(FeedValidationError, match="Suspicious"):
        reconcile_events(existing, [existing[0]], "timeedit", now=NOW)

    shifted = [event("timeedit", "new", "New window", "2026-03-01 09:00", "2026-03-01 10:00")]
    result = reconcile_events(existing, shifted, "timeedit", now=NOW)
    assert len(result) == 9
