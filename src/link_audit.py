#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlunparse

QMD_GLOB = "**/*.qmd"

# Inline: [text](url "title")
INLINE_LINK_RE = re.compile(r"\[([^\]]+)\]\((\S+?)(?:\s+\"[^\"]*\")?\)")
# Reference: [text][id] and [id]: url
REF_LINK_USE_RE = re.compile(r"\[([^\]]+)\]\[([^\]]+)\]")
REF_DEF_RE = re.compile(r"^\[([^\]]+)\]:\s*(\S+)", re.MULTILINE)

# Also catch raw autolinks <https://...>
AUTO_LINK_RE = re.compile(r"<(https?://[^>]+)>")

def normalize_url(url: str) -> str:
    url = url.strip().strip(")")
    # remove surrounding <>
    if url.startswith("<") and url.endswith(">"):
        url = url[1:-1]
    parsed = urlparse(url)
    if not parsed.scheme:
        return url  # likely relative path or anchor
    # drop fragment for "system" grouping; keep full later if you want
    clean = parsed._replace(fragment="")
    return urlunparse(clean)

def is_external(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")

def system_key(url: str) -> str:
    """Group into 'systems' by hostname (or 'internal')."""
    if not is_external(url):
        return "internal"
    host = urlparse(url).netloc.lower()
    # optional: compress common host variants
    host = host.removeprefix("www.")
    return host

@dataclass
class LinkRow:
    file: str
    text: str
    url: str
    external: bool
    system: str

def extract_links_from_text(text: str) -> tuple[list[tuple[str, str]], dict[str, str]]:
    """Return (inline_links[(text,url)], ref_defs{id:url})."""
    inline = [(m.group(1), m.group(2)) for m in INLINE_LINK_RE.finditer(text)]
    auto = [("autolink", m.group(1)) for m in AUTO_LINK_RE.finditer(text)]
    ref_defs = {m.group(1): m.group(2) for m in REF_DEF_RE.finditer(text)}
    # reference uses resolved later
    ref_uses = [(m.group(1), m.group(2)) for m in REF_LINK_USE_RE.finditer(text)]
    resolved_refs = [(t, ref_defs.get(r, "")) for (t, r) in ref_uses if ref_defs.get(r)]
    return inline + auto + resolved_refs, ref_defs

def main(project_root: str = ".") -> None:
    root = Path(project_root).resolve()
    qmd_files = sorted(root.glob(QMD_GLOB))

    rows: list[LinkRow] = []
    for fp in qmd_files:
        # skip output/venv if needed:
        if any(part in {"_site", "_book", ".quarto", ".venv", "venv", "node_modules"} for part in fp.parts):
            continue

        text = fp.read_text(encoding="utf-8", errors="ignore")
        links, _ = extract_links_from_text(text)

        for link_text, url in links:
            url_norm = normalize_url(url)
            ext = is_external(url_norm)
            sys = system_key(url_norm)
            rows.append(LinkRow(str(fp.relative_to(root)), link_text, url_norm, ext, sys))

    # Basic stats
    total = len(rows)
    external = sum(1 for r in rows if r.external)
    internal = total - external

    by_system = Counter(r.system for r in rows)
    by_file = Counter(r.file for r in rows)

    # "Key links" per system: most frequent URLs inside that system
    urls_by_system: dict[str, Counter[str]] = defaultdict(Counter)
    for r in rows:
        urls_by_system[r.system][r.url] += 1

    key_links = {
        sys: [{"url": u, "count": c} for (u, c) in urls_by_system[sys].most_common(10)]
        for sys in by_system.keys()
    }

    out_dir = root / "_link_audit"
    out_dir.mkdir(exist_ok=True)

    # Write rows
    with (out_dir / "links.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["file", "text", "url", "external", "system"])
        for r in rows:
            w.writerow([r.file, r.text, r.url, int(r.external), r.system])

    # Write summary
    summary = {
        "total_links": total,
        "external_links": external,
        "internal_links": internal,
        "systems": by_system.most_common(),
        "files": by_file.most_common(),
        "key_links": key_links,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Wrote: {out_dir/'links.csv'} and {out_dir/'summary.json'}")

if __name__ == "__main__":
    main(".")
