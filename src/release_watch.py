#!/usr/bin/env python3
"""
- Checks PyPI for latest versions of all BibTeX items with ENTRYTYPE == "software"
- Updates data/references.bib (stores version in a 'version' field; refreshes 'urldate')
- Detects newly added non-software records (no 'news_announced' field)
- Drafts one dated Quarto news post in news/posts/ for newly detected items
- Adds release notes (prefers GitHub Releases; falls back to a link if unavailable)
- references.bib remains the only state file
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

import colrev.loader.load_utils
import colrev.writer.write_utils


REFERENCES_BIB = Path("data/references.bib")
NEWS_POSTS_DIR = Path("news/posts")

PYPI_PROJECT_URL = "https://pypi.org/pypi/{project}/json"
GITHUB_API_LATEST_RELEASE = "https://api.github.com/repos/{owner}/{repo}/releases/latest"
GITHUB_API_TAG_RELEASE = "https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"

MAX_RELEASE_NOTES_CHARS = 1200
MAX_DESCRIPTION_CHARS = 220


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


def ensure_news_posts_dir_exists(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "news-item"


def yaml_double_quote(value: str) -> str:
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'


def yaml_folded(value: str, indent: str = "  ") -> str:
    words = str(value).split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > 78 and current:
            lines.append(indent + current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(indent + current)
    return "\n".join(lines) or indent


def truncate_description(value: str) -> str:
    value = " ".join(str(value).split())
    if len(value) <= MAX_DESCRIPTION_CHARS:
        return value
    return value[: MAX_DESCRIPTION_CHARS - 1].rsplit(" ", 1)[0].rstrip() + "…"


def unique_news_post_path(posts_dir: Path, date: str, slug: str) -> Path:
    candidate = posts_dir / f"{date}-{slug}.qmd"
    if not candidate.exists():
        return candidate
    i = 2
    while True:
        candidate = posts_dir / f"{date}-{slug}-{i}.qmd"
        if not candidate.exists():
            return candidate
        i += 1


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


def publication_title(rec: dict) -> str:
    return str(rec.get("title") or "Untitled publication")


def publication_description(new_pubs: List[tuple[str, dict]]) -> str:
    if len(new_pubs) == 1:
        _, rec = new_pubs[0]
        title = publication_title(rec)
        authors = rec.get("author", "")
        venue = rec.get("journal") or rec.get("booktitle") or ""
        parts = []
        if authors:
            parts.append(str(authors))
        parts.append(f'published "{title}"')
        if venue:
            parts.append(f"in {venue}")
        return truncate_description(" ".join(parts) + ".")
    return truncate_description(
        f"{len(new_pubs)} new publications were added to the handbook bibliography."
    )


def software_description(software_updates: List[ReleaseInfo]) -> str:
    if len(software_updates) == 1:
        rel = software_updates[0]
        return truncate_description(f"{rel.project} v{rel.version} was released.")
    versions = ", ".join(f"{rel.project} v{rel.version}" for rel in software_updates)
    return truncate_description(f"Software releases: {versions}.")


def build_news_post_front_matter(
    title: str,
    date: str,
    description: str,
    categories: List[str],
    external_url: Optional[str] = None,
) -> str:
    lines = [
        "---",
        f"title: {yaml_double_quote(title)}",
        f"date: {date}",
        "description: >",
        yaml_folded(description),
        "categories:",
    ]
    lines.extend(f"  - {category}" for category in categories)
    if external_url:
        lines.append(f"external-url: {external_url}")
    lines.append("---")
    return "\n".join(lines)


def draft_news_post(
    posts_dir: Path,
    new_pubs: List[tuple[str, dict]],
    software_updates: List[ReleaseInfo],
) -> Optional[Path]:
    if not new_pubs and not software_updates:
        return None

    ensure_news_posts_dir_exists(posts_dir)
    date = utc_date_iso()

    categories = []
    if new_pubs:
        categories.append("Publication")
    if software_updates:
        categories.append("Software")

    if new_pubs and not software_updates and len(new_pubs) == 1:
        _, rec = new_pubs[0]
        title = publication_title(rec)
        description = publication_description(new_pubs)
        external_url = rec.get("url", "") or None
        slug = slugify(title)[:60].strip("-")
    elif software_updates and not new_pubs:
        if len(software_updates) == 1:
            rel = software_updates[0]
            title = f"{rel.project} v{rel.version} released"
            external_url = rel.pypi_url
            slug = slugify(f"{rel.project}-{rel.version}")
        else:
            title = "Software releases"
            external_url = None
            slug = "software-releases"
        description = software_description(software_updates)
    else:
        title = "Publication and software updates"
        description = truncate_description(
            f"{len(new_pubs)} publication update(s) and {len(software_updates)} software release(s) were added."
        )
        external_url = None
        slug = "publication-software-updates"

    lines = [build_news_post_front_matter(title, date, description, categories, external_url)]

    body: List[str] = []
    if new_pubs and (len(new_pubs) > 1 or software_updates):
        body.extend(["", "## Publications", ""])
        for _, rec in sorted(new_pubs, key=lambda x: x[1].get("year", ""), reverse=True):
            title = publication_title(rec)
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
                entry += f" — <{url}>"
            body.append(entry)

    if software_updates:
        if new_pubs or len(software_updates) > 1:
            body.extend(["", "## Software", ""])

        for rel in sorted(software_updates, key=lambda x: x.project.lower()):
            body.append(f"- **{rel.project}** v{rel.version}: <{rel.pypi_url}>")

            if rel.release_notes:
                body.append("\n  Release notes:\n")
                for ln in _trim_notes(rel.release_notes).splitlines():
                    stripped = ln.strip()
                    if stripped:
                        body.append(f"  - {stripped.lstrip('-* ')}")
                body.append("")
            elif rel.release_notes_url:
                body.append(f"\n  Release notes: <{rel.release_notes_url}>\n")

    if body:
        lines.append("\n".join(body).rstrip())

    path = unique_news_post_path(posts_dir, date, slug)
    path.write_text("\n\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


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
    # Draft news post + update state
    # -------------------------------------------------
    news_post = draft_news_post(NEWS_POSTS_DIR, new_pubs, software_updates)

    today = utc_date_iso()

    for rid, rec in new_pubs:
        rec["news_announced"] = today

    if software_updates or new_pubs:
        colrev.writer.write_utils.write_file(records, filename=str(REFERENCES_BIB))
        suffix = f" News post drafted at {news_post}." if news_post else ""
        print(f"[OK] references.bib updated and news updated.{suffix}")
    else:
        print("[OK] No changes detected.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
