#!/usr/bin/env python3
"""
- Checks PyPI for latest versions of all BibTeX items with ENTRYTYPE == "software"
- Updates data/references.bib (stores version in a 'version' field; refreshes 'urldate')
- Detects newly added non-software records (no 'news_announced' field)
- Appends ONE structured dated entry to news.qmd
- Adds release notes (prefers GitHub Releases; falls back to a link if unavailable)
- references.bib remains the only state file
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import requests

import colrev.loader.load_utils
import colrev.writer.write_utils


REFERENCES_BIB = Path("data/references.bib")
NEWS_QMD = Path("news.qmd")

PYPI_PROJECT_URL = "https://pypi.org/pypi/{project}/json"
GITHUB_API_LATEST_RELEASE = "https://api.github.com/repos/{owner}/{repo}/releases/latest"
GITHUB_API_TAG_RELEASE = "https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"

MAX_RELEASE_NOTES_CHARS = 1200


@dataclass(frozen=True)
class ReleaseInfo:
    record_id: str
    project: str
    version: str
    pypi_url: str
    release_notes: Optional[str] = None
    release_notes_url: Optional[str] = None


def utc_date_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ---------------------------------------------------------------------
# PyPI + GitHub
# ---------------------------------------------------------------------

def fetch_latest_from_pypi(project: str, timeout: int = 20):
    url = PYPI_PROJECT_URL.format(project=project)
    r = requests.get(url, timeout=timeout)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    return data["info"]["version"], data["info"]["package_url"], data


def extract_github_repo(rec: dict) -> Optional[Tuple[str, str]]:
    gh = (rec.get("url_github") or "").strip()
    if not gh:
        return None
    m = re.search(r"github\.com/([^/]+)/([^/#?]+)", gh, flags=re.IGNORECASE)
    if not m:
        return None
    owner, repo = m.group(1), re.sub(r"\.git$", "", m.group(2))
    return owner, repo


def fetch_github_release_notes(owner: str, repo: str, version: str, timeout: int = 20):
    session = requests.Session()
    session.headers.update({"Accept": "application/vnd.github+json"})

    for tag in (f"v{version}", version):
        url = GITHUB_API_TAG_RELEASE.format(owner=owner, repo=repo, tag=tag)
        r = session.get(url, timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            return data.get("body"), data.get("html_url")

    url = GITHUB_API_LATEST_RELEASE.format(owner=owner, repo=repo)
    r = session.get(url, timeout=timeout)
    if r.status_code != 200:
        return None, None
    data = r.json()
    return data.get("body"), data.get("html_url")


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def is_software_record(rec: dict) -> bool:
    return (rec.get("ENTRYTYPE") or "").lower() == "software"


def extract_pypi_project(rec: dict) -> Optional[str]:
    pypi = (rec.get("url_pypi") or "").strip()
    if pypi.startswith("https://pypi.org/project/"):
        return pypi.rstrip("/").split("/")[-1]
    return None


def ensure_news_file_exists(path: Path):
    if path.exists():
        return
    path.write_text(
        "---\n"
        'title: "News"\n'
        "format: html\n"
        "---\n\n"
        "# News\n\n",
        encoding="utf-8",
    )


def _trim_notes(text: str) -> str:
    text = (text or "").strip()
    if len(text) <= MAX_RELEASE_NOTES_CHARS:
        return text
    return text[: MAX_RELEASE_NOTES_CHARS - 1].rstrip() + "…"


# ---------------------------------------------------------------------
# News logic
# ---------------------------------------------------------------------

def collect_new_publications(records: Dict[str, dict]):
    new_pubs = []
    for rid, rec in records.items():
        if not isinstance(rec, dict):
            continue
        if is_software_record(rec):
            continue
        if rec.get("news_announced"):
            continue
        new_pubs.append((rid, rec))
    return new_pubs


def update_software_versions(records, releases):
    changed = []
    for rel in releases:
        rec = records.get(rel.record_id)
        if rec.get("version") != rel.version:
            rec["version"] = rel.version
            rec["urldate"] = utc_date_iso()
            changed.append(rel)
    return changed


def prepend_news_entry(path: Path,
                       new_pubs: List[tuple[str, dict]],
                       software_updates: List[ReleaseInfo]):

    if not new_pubs and not software_updates:
        return

    ensure_news_file_exists(path)
    date = utc_date_iso()

    lines = [f"\n## {date}\n"]

    # -------------------------------------------------
    # New publications
    # -------------------------------------------------
    if new_pubs:
        lines.append("\n### ✨ New Publications\n\n")

        for rid, rec in sorted(new_pubs, key=lambda x: x[1].get("year", ""), reverse=True):
            title = rec.get("title", "Untitled")
            author = rec.get("author", "")
            year = rec.get("year", "")
            venue = rec.get("journal") or rec.get("booktitle") or ""
            url = rec.get("url", "")

            entry = f"- **{title}**"
            if year:
                entry += f" ({year})"
            if venue:
                entry += f", *{venue}*"
            if author:
                entry += f" — {author}"
            if url:
                entry += f" [{url}]"

            lines.append(entry + "\n")

    # -------------------------------------------------
    # Software updates
    # -------------------------------------------------
    if software_updates:
        lines.append("\n### 🔄 Software Updates\n\n")

        for rel in sorted(software_updates, key=lambda x: x.project.lower()):
            lines.append(f"- **{rel.project}** → v{rel.version} ({rel.pypi_url})\n")

            if rel.release_notes:
                lines.append("\n  Release notes:\n\n")
                for ln in _trim_notes(rel.release_notes).splitlines():
                    lines.append(f"  > {ln}\n")
                lines.append("\n")
            elif rel.release_notes_url:
                lines.append(f"\n  Release notes: {rel.release_notes_url}\n\n")

    existing = path.read_text(encoding="utf-8")

    if existing.startswith("---\n"):
        closing = existing.find("\n---\n", 4)
        if closing != -1:
            header_end = closing + len("\n---\n")
            header = existing[:header_end]
            body = existing[header_end:].lstrip("\n")
        else:
            header = ""
            body = existing.lstrip("\n")
    else:
        header = ""
        body = existing.lstrip("\n")

    new_block = "".join(lines).strip("\n")

    updated = ""
    if header:
        updated += header + "\n"
    updated += new_block + "\n"
    if body:
        updated += "\n" + body

    path.write_text(updated, encoding="utf-8")


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main():

    records = colrev.loader.load_utils.load(filename=str(REFERENCES_BIB))

    # -------------------------------------------------
    # Software: check PyPI
    # -------------------------------------------------
    software_items = []
    for rid, rec in records.items():
        if is_software_record(rec):
            project = extract_pypi_project(rec)
            if project:
                software_items.append((rid, project))

    projects = {project for _, project in software_items}

    latest_by_project = {}
    for project in projects:
        try:
            res = fetch_latest_from_pypi(project)
            if res:
                latest_by_project[project] = res
        except Exception:
            pass

    releases = []
    for rid, project in software_items:
        if project not in latest_by_project:
            continue
        version, pypi_url, _ = latest_by_project[project]
        rec = records[rid]

        notes = None
        notes_url = None

        gh = extract_github_repo(rec)
        if gh:
            try:
                notes, notes_url = fetch_github_release_notes(gh[0], gh[1], version)
            except Exception:
                pass

        releases.append(
            ReleaseInfo(
                record_id=rid,
                project=project,
                version=version,
                pypi_url=pypi_url,
                release_notes=notes,
                release_notes_url=notes_url,
            )
        )

    software_updates = update_software_versions(records, releases)

    # -------------------------------------------------
    # New publications
    # -------------------------------------------------
    new_pubs = collect_new_publications(records)

    # -------------------------------------------------
    # Write news + update state
    # -------------------------------------------------
    prepend_news_entry(NEWS_QMD, new_pubs, software_updates)

    today = utc_date_iso()

    for rid, rec in new_pubs:
        rec["news_announced"] = today

    if software_updates or new_pubs:
        colrev.writer.write_utils.write_file(records, filename=str(REFERENCES_BIB))
        print("[OK] references.bib updated and news updated.")
    else:
        print("[OK] No changes detected.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
