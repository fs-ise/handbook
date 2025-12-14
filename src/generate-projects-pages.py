#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


ROOT = Path(__file__).resolve().parents[1]
L_PATH = Path("data/projects.yml")
DATA_FILE = ROOT / L_PATH
OUT_DIR = ROOT / "research/projects"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Internal paper pages (site-relative, avoids 0.0.0.0:4200)
PAPERS_BASE_PATH = "/research/papers"


def _fmt_date(d: Optional[str]) -> str:
    if not d:
        return "—"
    return str(d)


def _is_github(link: Optional[str]) -> bool:
    return bool(link) and "github.com" in link


def _request_access_html(link: Optional[str]) -> str:
    if not _is_github(link):
        return "—"
    url = (
        "https://github.com/digital-work-lab/handbook/issues/new"
        "?assignees=geritwagner"
        "&labels=access+request"
        "&template=request-repo-access.md"
        "&title=%5BAccess+Request%5D+Request+for+access+to+repository"
    )
    return (
        f'<a href="{url}" target="_blank" rel="noopener">'
        f'<img src="https://img.shields.io/badge/Request-Access-blue" alt="Request Access">'
        f"</a>"
    )


def _resources_table(resources: List[Dict[str, Any]]) -> str:
    if not resources:
        return "—\n"

    lines: List[str] = []
    lines.append("| Name | Access | Last updated | Request |")
    lines.append("|---|---|---:|---|")

    for res in resources:
        name = res.get("name") or "—"
        link = res.get("link")
        access = res.get("access") or []
        last_updated = _fmt_date(res.get("last_updated"))

        if link:
            name_cell = f'[{name}]({link}){{target="_blank" rel="noopener"}}'
        else:
            name_cell = name

        if access:
            access_cell = ", ".join(
                [f"[{u}](https://github.com/{u}){{target=\"_blank\" rel=\"noopener\"}}" for u in access]
            )
        else:
            access_cell = "—"

        request_cell = _request_access_html(link)

        lines.append(f"| {name_cell} | {access_cell} | {last_updated} | {request_cell} |")

    return "\n".join(lines) + "\n"


def _history_block(history: List[Dict[str, Any]]) -> str:
    if not history:
        return "—\n"
    items: List[str] = []
    for h in history:
        items.append(f"- **{_fmt_date(h.get('date'))}** — {h.get('event','—')}")
    return "\n".join(items) + "\n"


def _output_block(project_output: Any) -> str:
    """
    Render manual links to internal paper pages, e.g.
    ## Output
    - [WagnerThurner2025](/research/papers/WagnerThurner2025.html)
    """
    if not isinstance(project_output, list):
        return ""

    keys = [k.strip() for k in project_output if isinstance(k, str) and k.strip()]
    if not keys:
        return ""

    lines: List[str] = []
    lines.append("## Output")
    for k in keys:
        lines.append(f"- [{k}]({PAPERS_BASE_PATH}/{k}.html)")
    return "\n".join(lines) + "\n"


def _frontmatter(project: Dict[str, Any]) -> str:
    pid = project["id"]

    fm: Dict[str, Any] = {
        "title": pid,
        "status": project.get("status", "planned"),
        "associated_projects": project.get("associated_projects", []),
        "collaborators": project.get("collaborators", []),
        "project_resources": project.get("project_resources", []),
        "project_history": project.get("project_history", []),
        # for convenience in listings
        "project_id": pid,
        "page_type": "project",
    }

    # Option C: do NOT add bibliography/csl/nocite/reference-section-title
    return "---\n" + yaml.safe_dump(fm, sort_keys=False).strip() + "\n---\n"


def render_project_page(project: Dict[str, Any]) -> str:
    pid = project["id"]
    status = project.get("status", "planned")
    collaborators = project.get("collaborators", [])
    collab_str = ", ".join(collaborators) if collaborators else "—"

    resources_md = _resources_table(project.get("project_resources", []))
    history_md = _history_block(project.get("project_history", []))
    output_md = _output_block(project.get("project_output", []))

    info_callout = f"""
::: {{.callout-note icon=false}}
This page is auto-generated. The authoritative project metadata is stored in
[`data/projects.yml`](https://github.com/fs-ise/handbook/tree/main/{L_PATH.as_posix()}).
:::
""".strip()

    # Output moved to *after* History
    body = f"""

{info_callout}

Field | Value
---|---
Acronym | `{pid}`
Team | {collab_str}
Status | `{status}`

## Resources
{resources_md}

## History
{history_md}

{output_md}
""".lstrip()

    return _frontmatter(project) + "\n" + body


def main() -> None:
    projects = yaml.safe_load(DATA_FILE.read_text(encoding="utf-8"))
    if not isinstance(projects, list):
        raise SystemExit("projects.yml must be a list of project entries")

    for p in projects:
        pid = p["id"]
        out_file = OUT_DIR / f"{pid}.qmd"
        out_file.write_text(render_project_page(p), encoding="utf-8")

    print(f"Generated {len(projects)} project pages in {OUT_DIR}")


if __name__ == "__main__":
    main()
