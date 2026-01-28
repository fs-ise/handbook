#!/usr/bin/env python3
"""
- Checks PyPI for latest versions of all BibTeX items with ENTRYTYPE == "software"
- Updates data/references.bib (stores version in a 'version' field; refreshes 'urldate')
- Appends a dated entry to news.qmd only for items whose stored version changed in this run
- Adds release notes (prefers GitHub Releases; falls back to a link if unavailable)
- No separate state file: references.bib is the state
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

# Keep news readable
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


def fetch_latest_from_pypi(project: str, timeout: int = 20) -> Optional[tuple[str, str, dict]]:
    """
    Returns (latest_version, package_url, full_json) or None if project not found / fetch fails.
    """
    url = PYPI_PROJECT_URL.format(project=project)
    r = requests.get(url, timeout=timeout)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    version = data["info"]["version"]
    pypi_url = data["info"]["package_url"]
    return version, pypi_url, data


def ensure_news_file_exists(path: Path) -> None:
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
    text = text.strip()
    if len(text) <= MAX_RELEASE_NOTES_CHARS:
        return text
    return text[: MAX_RELEASE_NOTES_CHARS - 1].rstrip() + "…"


def append_news_entry(path: Path, releases: List[ReleaseInfo]) -> None:
    ensure_news_file_exists(path)
    date = utc_date_iso()

    lines: List[str] = [f"\n## {date}\n", "New releases:\n"]
    for rel in sorted(releases, key=lambda x: x.project.lower()):
        lines.append(f"- **{rel.project}** v{rel.version} ({rel.pypi_url})\n")

        if rel.release_notes:
            lines.append("\n  Release notes:\n\n")
            # Indent as a Quarto/Markdown block quote under the bullet
            for ln in _trim_notes(rel.release_notes).splitlines():
                lines.append(f"  > {ln}\n")
            lines.append("\n")
        elif rel.release_notes_url:
            lines.append(f"\n  Release notes: {rel.release_notes_url}\n\n")

    with path.open("a", encoding="utf-8") as f:
        f.writelines(lines)


def is_software_record(rec: dict) -> bool:
    entrytype = (rec.get("ENTRYTYPE") or rec.get("entrytype") or "").strip().lower()
    return entrytype == "software"


def extract_pypi_project(rec: dict) -> Optional[str]:
    """
    Determine the PyPI project name for a software record.
    Expects url_pypi like https://pypi.org/project/<name>/...
    """
    pypi = (rec.get("url_pypi") or rec.get("PyPI") or "").strip()
    if pypi and pypi.startswith("https://pypi.org/project/"):
        return pypi.rstrip("/").split("/")[-1]
    return None


def extract_github_repo(rec: dict) -> Optional[Tuple[str, str]]:
    """
    Extract (owner, repo) from url_github like:
      https://github.com/<owner>/<repo>
    """
    gh = (rec.get("url_github") or rec.get("github") or rec.get("GitHub") or "").strip()
    if not gh:
        return None
    m = re.search(r"github\.com/([^/]+)/([^/#?]+)", gh, flags=re.IGNORECASE)
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)
    # Strip a trailing ".git"
    repo = re.sub(r"\.git$", "", repo, flags=re.IGNORECASE)
    return owner, repo


def fetch_github_release_notes(owner: str, repo: str, version: str, timeout: int = 20) -> Tuple[Optional[str], Optional[str]]:
    """
    Try to retrieve release notes from GitHub Releases.

    Strategy:
    1) Try tag lookups for common tag patterns: v{version}, {version}
    2) Fall back to "latest release"
    Returns (body, html_url) or (None, None)
    """
    session = requests.Session()
    session.headers.update({"Accept": "application/vnd.github+json"})

    # Try tag-based first (often matches exactly the PyPI version)
    for tag in (f"v{version}", version):
        url = GITHUB_API_TAG_RELEASE.format(owner=owner, repo=repo, tag=tag)
        r = session.get(url, timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            body = (data.get("body") or "").strip()
            html_url = data.get("html_url")
            if body:
                return body, html_url
            return None, html_url

    # Fall back to latest (may not correspond to same version)
    url = GITHUB_API_LATEST_RELEASE.format(owner=owner, repo=repo)
    r = session.get(url, timeout=timeout)
    if r.status_code != 200:
        return None, None
    data = r.json()
    body = (data.get("body") or "").strip()
    html_url = data.get("html_url")
    return (body or None), html_url


def update_references_versions(records: Dict[str, dict], releases: List[ReleaseInfo]) -> List[ReleaseInfo]:
    """
    Updates 'version' (and 'urldate') for records where stored version differs.
    Returns the subset of releases that changed in this run (i.e., "new releases").
    """
    changed: List[ReleaseInfo] = []

    for rel in releases:
        rec = records.get(rel.record_id)
        if rec is None:
            continue

        old = rec.get("version")
        if old != rel.version:
            rec["version"] = rel.version
            rec["urldate"] = utc_date_iso()
            changed.append(rel)

    return changed


def main() -> int:
    if not REFERENCES_BIB.exists():
        raise FileNotFoundError(f"Missing {REFERENCES_BIB}")

    records = colrev.loader.load_utils.load(filename=str(REFERENCES_BIB))

    # Collect software records and their PyPI projects
    software_items: List[tuple[str, str]] = []
    for rid, rec in records.items():
        if not isinstance(rec, dict):
            continue
        if not is_software_record(rec):
            continue

        project = extract_pypi_project(rec)
        if not project:
            print(f"[WARN] Could not determine PyPI project for software record '{rid}' (missing/invalid url_pypi).")
            continue
        software_items.append((rid, project))

    if not software_items:
        print("[OK] No BibTeX items of type 'software' found.")
        return 0

    projects: Set[str] = {project for _, project in software_items}

    latest_by_project: Dict[str, tuple[str, str, dict]] = {}
    for project in sorted(projects, key=str.lower):
        try:
            res = fetch_latest_from_pypi(project)
            if res is None:
                print(f"[WARN] PyPI project not found: {project}")
                continue
            latest_by_project[project] = res
        except Exception as e:
            print(f"[WARN] Failed to fetch {project} from PyPI: {e}")

    if not latest_by_project:
        print("[WARN] No release info fetched; exiting without changes.")
        return 0

    # Build per-record list (includes release notes lookup context)
    releases: List[ReleaseInfo] = []
    for rid, project in software_items:
        if project not in latest_by_project:
            continue
        version, pypi_url, _pypi_json = latest_by_project[project]

        # Try GitHub release notes if we have url_github in the bib record
        rec = records.get(rid, {})
        notes = None
        notes_url = None
        gh = extract_github_repo(rec)
        if gh:
            try:
                notes, notes_url = fetch_github_release_notes(gh[0], gh[1], version=version)
            except Exception as e:
                print(f"[WARN] Failed to fetch GitHub release notes for {project}: {e}")

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

    # Update bib; changed items are "new releases"
    changed_in_bib = update_references_versions(records, releases)

    if changed_in_bib:
        colrev.writer.write_utils.write_file(records, filename=str(REFERENCES_BIB))
        print(f"[OK] Updated {len(changed_in_bib)} version field(s) in {REFERENCES_BIB}")

        append_news_entry(NEWS_QMD, changed_in_bib)
        print(f"[OK] Appended news entry for {len(changed_in_bib)} release(s) to {NEWS_QMD}")
    else:
        print("[OK] No new releases (versions unchanged).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
