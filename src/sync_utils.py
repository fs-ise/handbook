from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from zoneinfo import ZoneInfo

EVENTS_PATH = Path("data/events.yaml")
ICAL_PATH = Path("assets/calendar/fs-ise.ical")
BERLIN = ZoneInfo("Europe/Berlin")


class FeedValidationError(ValueError):
    """Raised before any published calendar file is changed."""


class QuotedValue(str):
    pass


class ValueQuotedDumper(yaml.SafeDumper):
    pass


def quoted_value_representer(dumper: yaml.Dumper, data: QuotedValue) -> yaml.Node:
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')


ValueQuotedDumper.add_representer(QuotedValue, quoted_value_representer)


def quote_string_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: quote_string_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [quote_string_values(item) for item in value]
    if isinstance(value, str):
        return QuotedValue(value)
    return value


def sort_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(events, key=lambda ev: (
        str(ev.get("start", "")), str(ev.get("title", "")),
        str(ev.get("source_uid", "")),
    ))


def events_yaml_text(events: list[dict[str, Any]]) -> str:
    return yaml.dump(
        quote_string_values(events), Dumper=ValueQuotedDumper,
        allow_unicode=True, default_flow_style=False, sort_keys=False, width=4096,
    )


def write_events_yaml(events: list[dict[str, Any]], path: Path = EVENTS_PATH) -> None:
    path.write_text(events_yaml_text(events), encoding="utf-8")


def event_end(event: dict[str, Any]) -> datetime:
    value = str(event.get("end", "")).strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FeedValidationError(f"Event has invalid end datetime {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=BERLIN)
    return parsed.astimezone(BERLIN)


def validate_incoming_events(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]], source: str,
    *, now: datetime | None = None,
) -> None:
    """Validate a parsed feed without mistaking expired history for feed loss."""
    if not incoming:
        raise FeedValidationError(f"{source} feed contains no importable events")

    seen: dict[str, dict[str, Any]] = {}
    for event in incoming:
        missing = [key for key in ("title", "start", "end", "source_uid") if not event.get(key)]
        if missing:
            raise FeedValidationError(
                f"{source} event is missing essential field(s): {', '.join(missing)}"
            )
        if event.get("source") != source:
            raise FeedValidationError(f"Incoming event has unexpected source {event.get('source')!r}")
        uid = str(event["source_uid"])
        if uid in seen:
            detail = "conflicting" if seen[uid] != event else "duplicate"
            raise FeedValidationError(f"{source} feed contains {detail} UID {uid!r}")
        seen[uid] = event
        event_end(event)

    current = now or datetime.now(BERLIN)
    if current.tzinfo is None:
        current = current.replace(tzinfo=BERLIN)
    future_existing = [
        event for event in existing
        if event.get("source") == source and event_end(event) >= current
    ]
    # Only flag a collapse of the still-relevant window. Historical entries rolling
    # out are deliberately excluded, and new UIDs demonstrate a moving window.
    old_uids = {str(event.get("source_uid")) for event in future_existing}
    future_incoming = [event for event in incoming if event_end(event) >= current]
    new_future_uids = {str(event["source_uid"]) for event in future_incoming}
    if (
        len(future_existing) >= 8
        and len(future_incoming) * 4 < len(future_existing)
        and not (new_future_uids - old_uids)
    ):
        raise FeedValidationError(
            f"Suspicious {source} feed reduction: {len(future_incoming)} incoming future events "
            f"for {len(future_existing)} existing future events"
        )


def reconcile_events(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]], source: str,
    *, now: datetime | None = None,
    missing_future_policy: Literal["preserve", "delete"] = "preserve",
) -> list[dict[str, Any]]:
    """Update events by (source, source_uid), retaining absent events safely.

    ``delete`` is intentionally opt-in and is only appropriate when a caller has
    independently established complete upstream coverage for the relevant range.
    """
    validate_incoming_events(existing, incoming, source, now=now)
    current = now or datetime.now(BERLIN)
    if current.tzinfo is None:
        current = current.replace(tzinfo=BERLIN)
    incoming_by_uid = {str(event["source_uid"]): event for event in incoming}
    result: list[dict[str, Any]] = []
    existing_keys: set[tuple[str, str]] = set()

    for event in existing:
        if event.get("source") != source:
            result.append(event)
            continue
        uid = str(event.get("source_uid") or "")
        key = (source, uid)
        if not uid:
            raise FeedValidationError(f"Existing {source} event has no source_uid")
        if key in existing_keys:
            raise FeedValidationError(f"Existing calendar contains duplicate {source} UID {uid!r}")
        existing_keys.add(key)
        replacement = incoming_by_uid.pop(uid, None)
        if replacement is not None:
            result.append(replacement)
        elif event_end(event) < current:
            result.append(event)
        elif missing_future_policy == "preserve":
            logging.warning(
                "Retaining future %s event missing from feed: UID=%s title=%s",
                source, uid, event.get("title", ""),
            )
            result.append(event)
        else:
            logging.warning("Deleting missing future %s event by explicit policy: UID=%s", source, uid)

    result.extend(incoming_by_uid.values())
    return sort_events(result)


def publish_calendar(
    events: list[dict[str, Any]], *, events_path: Path = EVENTS_PATH,
    ical_path: Path = ICAL_PATH,
) -> None:
    """Prepare both outputs, then replace them atomically with rollback on error."""
    from update_calendar import expand_events, generate_ical

    yaml_text = events_yaml_text(events)
    ical_text = generate_ical(expand_events(events))
    prepared = ((events_path, yaml_text), (ical_path, ical_text))
    temporary: list[tuple[Path, Path]] = []
    originals = {path: path.read_bytes() if path.exists() else None for path, _ in prepared}
    try:
        for path, text in prepared:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
                tmp.write(text)
                temporary.append((Path(tmp.name), path))
        for tmp, path in temporary:
            os.replace(tmp, path)
    except Exception:
        for path, content in originals.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)
        raise
    finally:
        for tmp, _ in temporary:
            tmp.unlink(missing_ok=True)
