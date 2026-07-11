"""Utilities for rendering course overviews in Quarto pages."""
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
COURSES_DIR = ROOT / "teaching" / "courses"
ACTIVE_STATUSES = {"in-progress", "grading", "upcoming"}


def markdown_link(label: str, url: str) -> str:
    """Return a Markdown link unless the URL is empty or still pending."""
    if not url or "pending" in url.lower():
        return label
    return f'[{label}]({url}){{target="_blank"}}'


def course_page(path: Path) -> str:
    """Return the handbook page URL for a course source file."""
    return f"/teaching/courses/{path.stem}.html"


def read_course(path: Path) -> dict[str, str]:
    """Read top-level scalar values from a course file's YAML front matter."""
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", text, flags=re.DOTALL)
    if not match:
        return {}

    metadata: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line.startswith(" "):
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip("\"'")
    metadata["admin"] = course_page(path)
    return metadata


def active_courses() -> list[dict[str, str]]:
    """Return active course metadata sorted for display."""
    courses = []
    course_files = [*COURSES_DIR.glob("*.qmd"), *COURSES_DIR.glob("*.md")]
    for path in sorted(course_files):
        metadata = read_course(path)
        if str(metadata.get("status", "")).lower() in ACTIVE_STATUSES:
            courses.append(metadata)

    return sorted(courses, key=lambda course: (course.get("semester", ""), course.get("title", "")))


def current_upcoming_courses_markdown() -> str:
    """Render the current/upcoming courses overview as a Markdown table."""
    lines = [
        "| Semester | Course | Status | Admin |",
        "| --- | --- | --- | --- |",
    ]
    for course in active_courses():
        title = str(course.get("title", "Untitled course"))
        page = str(course.get("page", ""))
        lines.append(
            "| {semester} | {course} | {status} | [Handbook]({admin}) |".format(
                semester=course.get("semester", ""),
                course=markdown_link(title, page),
                status=course.get("status", ""),
                admin=course.get("admin", ""),
            )
        )
    return "\n".join(lines)


if __name__ == "__main__":
    print(current_upcoming_courses_markdown())
