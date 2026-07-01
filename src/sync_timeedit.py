#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml
from icalendar import Calendar
from update_calendar import main as update_calendar_main
from zoneinfo import ZoneInfo


TIMEEDIT_ICAL_URL = "https://cloud.timeedit.net/de_frankfurt_school/web/employees/ri66Qv2Z56Y99dQYQ6Qun22XZo00Qwt118mZnZ7ym55Z0Y4620nQo4558Bt8980E66367C3B70m7kBQnF4341ZC27j4olA87501287C.ics"
EVENTS_PATH = Path("data/events.yaml")
BERLIN = ZoneInfo("Europe/Berlin")
NON_LECTURE_TITLE_PARTS = (
    "orientation",
    "exam week",
    "career day",
    "scholarship ceremony",
    "startup night",
    "bachelor day",
    "mba reunion",
    "alumni homecoming",
    "weihnachtsfeiertag",
    "neujahrstag",
    "tag der deutschen einheit",
    "karfreitag",
    "ostersonntag",
    "ostermontag",
    "tag der arbeit",
    "christi himmelfahrt",
    "pfingstsonntag",
    "pfingstmontag",
    "fronleichnam",
)

class QuotedValue(str):
    pass


class ValueQuotedDumper(yaml.SafeDumper):
    pass


def quoted_value_representer(dumper: yaml.Dumper, data: QuotedValue) -> yaml.Node:
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')


ValueQuotedDumper.add_representer(QuotedValue, quoted_value_representer)


def quote_string_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: quote_string_values(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [quote_string_values(item) for item in value]
    if isinstance(value, str):
        return QuotedValue(value)
    return value

def fetch_timeedit_ical() -> bytes:
    request = urllib.request.Request(
        TIMEEDIT_ICAL_URL,
        headers={"User-Agent": "fs-ise-handbook-timeedit-sync/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def as_berlin_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    else:
        raise TypeError(f"Unsupported iCalendar datetime value: {value!r}")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BERLIN)
    return dt.astimezone(BERLIN)


def format_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def component_text(component: Any, name: str) -> str:
    value = component.get(name)
    return "" if value is None else str(value).strip()


def stable_source_uid(title: str, start: str, end: str, location: str) -> str:
    digest = hashlib.sha256(
        "\u241f".join([title, start, end, location]).encode("utf-8")
    ).hexdigest()
    return digest[:24]


def is_lecture_event(title: str, start: str, end: str) -> bool:
    normalized_title = " ".join(title.casefold().split())
    if not normalized_title:
        return False
    if start == end:
        return False
    if title.strip().endswith(", 0"):
        return False
    return not any(part in normalized_title for part in NON_LECTURE_TITLE_PARTS)


def event_from_component(component: Any) -> dict[str, str] | None:
    title = component_text(component, "summary")
    location = component_text(component, "location")
    start = format_dt(as_berlin_datetime(component.decoded("dtstart")))
    end = format_dt(as_berlin_datetime(component.decoded("dtend")))
    if not is_lecture_event(title, start, end):
        return None

    source_uid = component_text(component, "uid") or stable_source_uid(
        title, start, end, location
    )

    event = {
        "title": title,
        "start": start,
        "end": end,
    }
    if location:
        event["location"] = location
    event["source"] = "timeedit"
    event["source_uid"] = source_uid
    return event


def parse_timeedit_events(ical_bytes: bytes) -> list[dict[str, str]]:
    calendar = Calendar.from_ical(ical_bytes)
    events = []
    for component in calendar.walk("VEVENT"):
        event = event_from_component(component)
        if event is not None:
            events.append(event)

    return sorted(
        events,
        key=lambda ev: (ev["start"], ev["title"], ev["source_uid"]),
    )


def sort_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        events,
        key=lambda ev: (
            str(ev.get("start", "")),
            str(ev.get("title", "")),
            str(ev.get("source_uid", "")),
        ),
    )


def write_events_yaml(events: list[dict[str, Any]]) -> None:
    text = yaml.dump(
        quote_string_values(events),
        Dumper=ValueQuotedDumper,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=4096,
    )
    EVENTS_PATH.write_text(text, encoding="utf-8")


def main() -> None:
    raw = yaml.safe_load(EVENTS_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Parsed YAML is not a list")

    manual_events = [ev for ev in raw if ev.get("source") != "timeedit"]
    timeedit_events = parse_timeedit_events(fetch_timeedit_ical())
    combined_events = sort_events([*manual_events, *timeedit_events])
    write_events_yaml(combined_events)
    print(f"Wrote {len(timeedit_events)} TimeEdit events to {EVENTS_PATH}")
    update_calendar_main()


if __name__ == "__main__":
    main()
