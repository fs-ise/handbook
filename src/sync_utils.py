from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

EVENTS_PATH = Path("data/events.yaml")


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
    return sorted(
        events,
        key=lambda ev: (
            str(ev.get("start", "")),
            str(ev.get("title", "")),
            str(ev.get("source_uid", "")),
        ),
    )


def write_events_yaml(events: list[dict[str, Any]], path: Path = EVENTS_PATH) -> None:
    text = yaml.dump(
        quote_string_values(events),
        Dumper=ValueQuotedDumper,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=4096,
    )
    path.write_text(text, encoding="utf-8")
