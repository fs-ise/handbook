#!/usr/bin/env python3
from __future__ import annotations

import uuid
from pathlib import Path
from datetime import datetime, timedelta

import yaml
from dateutil import rrule
from dateutil.parser import isoparse
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event


BERLIN = ZoneInfo("Europe/Berlin")


def parse_dt(value: str) -> datetime:
    """
    Accepts:
      - "YYYY-MM-DD HH:MM"
      - ISO strings like "2025-01-17T13:00:00Z" / "2025-01-17T13:00:00+01:00"
    Returns timezone-aware datetime in Europe/Berlin.
    """
    value = value.strip()
    if "T" in value:  # ISO-ish
        dt = isoparse(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=BERLIN)
        return dt.astimezone(BERLIN)

    # "YYYY-MM-DD HH:MM"
    dt = datetime.strptime(value, "%Y-%m-%d %H:%M")
    return dt.replace(tzinfo=BERLIN)


def expand_events(events: list[dict]) -> list[dict]:
    expanded: list[dict] = []

    for ev in events:
        start = parse_dt(ev["start"])
        end = parse_dt(ev["end"])
        duration = end - start

        if "recurrence" in ev and ev["recurrence"]:
            # RRULE.parseString equivalent:
            rule = rrule.rrulestr(ev["recurrence"], dtstart=start)

            for occ_start in rule:
                occ_end = occ_start + duration
                expanded.append(
                    {
                        "start": occ_start,
                        "end": occ_end,
                        "title": ev.get("title", ""),
                        "location": ev.get("location", ""),
                        "description": ev.get("description", ""),
                        "color": ev.get("color", ""),
                    }
                )
        else:
            expanded.append(
                {
                    "start": start,
                    "end": end,
                    "title": ev.get("title", ""),
                    "location": ev.get("location", ""),
                    "description": ev.get("description", ""),
                    "color": ev.get("color", ""),
                }
            )

    return expanded


def generate_ical(events: list[dict]) -> str:
    cal = Calendar()
    cal.add("prodid", "-//FS-ISE Lab//Calendar Export Tool//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    # Optional: many clients ignore this, but harmless
    cal.add("x-published-ttl", "PT1H")

    now_utc = datetime.now(tz=ZoneInfo("UTC"))

    for ev in events:
        e = Event()
        e.add("uid", f"{uuid.uuid4()}@fs-ise")
        e.add("dtstamp", now_utc)
        e.add("summary", ev.get("title", "") or " ")
        e.add("dtstart", ev["start"])
        e.add("dtend", ev["end"])

        desc = ev.get("description") or ""
        loc = ev.get("location") or ""
        if desc:
            e.add("description", desc)
        if loc:
            e.add("location", loc)

        # NOTE: "color" is not a standard iCalendar VEVENT property.
        # Some clients support non-standard props like COLOR or CATEGORIES.
        # If you want to encode it anyway:
        if ev.get("color"):
            e.add("x-apple-calendar-color", ev["color"])
            e.add("color", ev["color"])  # non-standard, but some tools read it

        cal.add_component(e)

    return cal.to_ical().decode("utf-8")


def main() -> None:
    yaml_path = Path("./data/events.yaml")
    out_path = Path("assets/calendar/fs-ise.ical")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Parsed YAML is not a list")

    expanded = expand_events(raw)
    ical_text = generate_ical(expanded)

    out_path.write_text(ical_text, encoding="utf-8")
    print(f"Wrote {len(expanded)} events to {out_path}")


if __name__ == "__main__":
    main()
