#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from typing import Any

import yaml
from dateutil import parser as date_parser
from sync_utils import EVENTS_PATH, sort_events, write_events_yaml
from update_calendar import main as update_calendar_main

AISNET_ICAL_URL = "https://aisnet.org/events/list/?ical=1"
USER_AGENT = "fs-ise-handbook-aisnet-sync/1.0"
TARGET_RE = re.compile(
    r"(?<![A-Za-z])(?:ECIS|ICIS)(?![A-Za-z])"
    r"|European Conference on Information Systems"
    r"|International Conference on Information Systems",
    re.IGNORECASE,
)
EXCLUDED_RE = re.compile(r"(?<![A-Za-z])(?:AMCIS|PACIS)(?![A-Za-z])", re.IGNORECASE)


def normalize_space(value: str) -> str:
    return " ".join(value.split())


def fetch_aisnet_ical() -> str:
    request = urllib.request.Request(
        AISNET_ICAL_URL, headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read().decode(
                response.headers.get_content_charset() or "utf-8", "replace"
            )
    except Exception as exc:
        raise RuntimeError(f"Could not fetch {AISNET_ICAL_URL}: {exc}") from exc


def is_target_event(text: str) -> bool:
    return bool(TARGET_RE.search(text)) and not bool(EXCLUDED_RE.search(text))


def unfold_ical_lines(ical_text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in ical_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw_line.startswith((" ", "\t")) and lines:
            lines[-1] += raw_line[1:]
        else:
            lines.append(raw_line)
    return lines


def unescape_ical_text(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\N", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def parse_ical_property(line: str) -> tuple[str, dict[str, str], str] | None:
    if ":" not in line:
        return None
    name_and_params, value = line.split(":", 1)
    parts = name_and_params.split(";")
    name = parts[0].upper()
    params: dict[str, str] = {}
    for part in parts[1:]:
        if "=" in part:
            key, param_value = part.split("=", 1)
            params[key.upper()] = param_value
    return name, params, unescape_ical_text(value)


def parse_aisnet_ical_events(ical_text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for line in unfold_ical_lines(ical_text):
        if line == "BEGIN:VEVENT":
            current = {"_date_only": {}}
            continue
        if line == "END:VEVENT":
            if current is not None:
                events.append(current)
            current = None
            continue
        if current is None:
            continue

        parsed = parse_ical_property(line)
        if not parsed:
            continue
        name, params, value = parsed
        if name in {"SUMMARY", "DESCRIPTION", "LOCATION", "URL", "UID"}:
            current[name.lower()] = normalize_space(value)
        elif name in {"DTSTART", "DTEND"}:
            parsed_date = parse_ical_date(value)
            if parsed_date:
                current[name.lower()] = parsed_date
                current["_date_only"][name.lower()] = (
                    params.get("VALUE", "").upper() == "DATE" or "T" not in value
                )

    return events


def parse_ical_date(value: str) -> date | None:
    value = value.strip()
    if not value:
        return None
    try:
        return datetime.strptime(value[:8], "%Y%m%d").date()
    except ValueError:
        pass
    try:
        return date_parser.parse(value).date()
    except (ValueError, OverflowError):
        return None


def source_uid_for(event: dict[str, Any], start: str, end: str, location: str) -> str:
    url = str(event.get("url") or "")
    uid = str(event.get("uid") or "")
    if url:
        basis = urllib.parse.urljoin(AISNET_ICAL_URL, url)
    elif uid:
        basis = uid
    else:
        basis = "\u241f".join([str(event.get("summary") or ""), start, end, location])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]


def event_from_ical_event(ical_event: dict[str, Any]) -> dict[str, str] | None:
    searchable_text = normalize_space(
        " ".join(
            str(ical_event.get(key) or "")
            for key in ("summary", "description", "location", "url")
        )
    )
    if not is_target_event(searchable_text):
        return None

    start_date = ical_event.get("dtstart")
    if not isinstance(start_date, date):
        return None
    end_date = (
        ical_event.get("dtend")
        if isinstance(ical_event.get("dtend"), date)
        else start_date
    )
    date_only = ical_event.get("_date_only", {})
    if date_only.get("dtend") and end_date > start_date:
        end_date = end_date - timedelta(days=1)

    title = normalize_space(str(ical_event.get("summary") or ""))
    location = normalize_space(str(ical_event.get("location") or ""))
    event = {
        "title": title,
        "start": f"{start_date:%Y-%m-%d} 09:00",
        "end": f"{end_date:%Y-%m-%d} 17:00",
        "source": "aisnet",
        "source_uid": "",
    }
    if location:
        event["location"] = location
    if ical_event.get("url"):
        event["description"] = str(ical_event["url"])
    event["source_uid"] = source_uid_for(
        event=ical_event,
        start=event["start"],
        end=event["end"],
        location=location,
    )
    return event


def parse_aisnet_events(ical_text: str) -> list[dict[str, str]]:
    parsed_events = parse_aisnet_ical_events(ical_text)
    events_by_uid: dict[str, dict[str, str]] = {}
    for parsed_event in parsed_events:
        event = event_from_ical_event(parsed_event)
        if event:
            events_by_uid[event["source_uid"]] = event
    events = sort_events(list(events_by_uid.values()))
    if not events and TARGET_RE.search(ical_text):
        raise ValueError(
            "Found ECIS/ICIS text in AISNET iCalendar export but could not parse "
            "any dated events"
        )
    return events


def main() -> None:
    raw = yaml.safe_load(EVENTS_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Parsed YAML is not a list")
    aisnet_events = parse_aisnet_events(fetch_aisnet_ical())
    preserved_events = [ev for ev in raw if ev.get("source") != "aisnet"]
    write_events_yaml(sort_events([*preserved_events, *aisnet_events]))
    print(f"Wrote {len(aisnet_events)} AISNET events to {EVENTS_PATH}")
    update_calendar_main()


if __name__ == "__main__":
    main()
