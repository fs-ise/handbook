"""Utilities for rendering course overviews in Quarto pages."""
from __future__ import annotations

from html import escape
from pathlib import Path
import re
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

from src.course_registry import load_course_registry, resolve_course_metadata

COURSES_DIR = ROOT / "teaching" / "courses"
ACTIVE_STATUSES = {"in-progress", "grading", "upcoming"}
STATUS_ORDER = {"in-progress": 0, "grading": 1, "upcoming": 2, "completed": 3}
PLACEHOLDER_IMAGE = "/assets/images/course-placeholder.svg"


def markdown_link(label: str, url: str) -> str:
    """Return a Markdown link unless the URL is empty or still pending."""
    if not valid_public_page(url):
        return label
    return f'[{label}]({url}){{target="_blank"}}'


def valid_public_page(value: Any) -> bool:
    """Return whether a value is a usable HTTP(S) course-page URL."""
    return isinstance(value, str) and value.startswith(("https://", "http://")) and "pending" not in value.lower()


def course_page(path: Path) -> str:
    """Return the handbook page URL for a course source file."""
    return f"/teaching/courses/{path.stem}.html"


def read_course(path: Path) -> dict[str, str]:
    """Read top-level scalar values from a course file's YAML front matter."""
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\r?\n(.*?)\r?\n---", text, flags=re.DOTALL)
    if not match:
        return {}

    metadata: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line.startswith((" ", "\t")):
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip("\"'")
    metadata["admin"] = course_page(path)
    return metadata


def _semester_key(semester: str) -> tuple[int, int, str]:
    """Build a descending-friendly chronological key for handbook semesters."""
    match = re.match(r"^(\d{4})-(WiSe|SuSe|SoSe)$", semester)
    if not match:
        return (0, 0, semester)
    term = 1 if match.group(2) == "WiSe" else 0
    return (int(match.group(1)), term, semester)


def all_courses() -> list[dict[str, Any]]:
    """Return every offering enriched by canonical registry metadata."""
    courses: list[dict[str, Any]] = []
    registry = load_course_registry()
    course_files = [*COURSES_DIR.glob("*.qmd"), *COURSES_DIR.glob("*.md")]
    for path in sorted(course_files):
        offering: dict[str, Any] = read_course(path)
        course_id, definition = resolve_course_metadata(offering, registry, path)
        offering["course_id"] = course_id
        # Titles and presentation fields are deliberately canonical course-level data.
        offering["title"] = definition["title"]
        offering["description"] = definition.get("description", "")
        offering["image"] = definition.get("image", "")
        courses.append(offering)

    # Sort title first, then descending semester, then prescribed status. Python's
    # stable sort keeps the earlier keys intact within each subsequent group.
    courses.sort(key=lambda course: str(course["title"]).casefold())
    courses.sort(key=lambda course: _semester_key(str(course.get("semester", ""))), reverse=True)
    courses.sort(key=lambda course: STATUS_ORDER.get(str(course.get("status", "")).lower(), 99))
    return courses


def active_courses() -> list[dict[str, Any]]:
    """Return active course metadata in carousel display order."""
    return [course for course in all_courses() if str(course.get("status", "")).lower() in ACTIVE_STATUSES]


def current_upcoming_courses_markdown() -> str:
    """Render the current/upcoming courses overview as a Markdown table."""
    lines = ["| Semester | Course | Status | Admin |", "| --- | --- | --- | --- |"]
    for course in active_courses():
        lines.append(
            "| {semester} | {course} | {status} | [Handbook]({admin}) |".format(
                semester=course.get("semester", ""),
                course=markdown_link(str(course.get("title", "Untitled course")), str(course.get("page", ""))),
                status=course.get("status", ""),
                admin=course.get("admin", ""),
            )
        )
    return "\n".join(lines)


def _local_image(image: Any) -> str:
    """Return a published local image path, falling back when it is absent."""
    if not isinstance(image, str) or not image.strip():
        return PLACEHOLDER_IMAGE
    web_path = "/" + image.strip().lstrip("/")
    return web_path if (ROOT / web_path.lstrip("/")).is_file() else PLACEHOLDER_IMAGE


def course_cards_html() -> str:
    """Render all offerings as an accessible, horizontally scrolling carousel."""
    cards: list[str] = []
    for index, course in enumerate(all_courses(), start=1):
        title = escape(str(course.get("title", "Untitled course")))
        description = escape(str(course.get("description", "")))
        semester = escape(str(course.get("semester", "")))
        status_value = str(course.get("status", "")).lower()
        status = escape(status_value)
        image = escape(_local_image(course.get("image")), quote=True)
        admin = escape(str(course["admin"]), quote=True)
        public_action = ""
        if valid_public_page(course.get("page")):
            page = escape(str(course["page"]), quote=True)
            public_action = f'<a class="course-card__action course-card__action--primary" href="{page}" target="_blank" rel="noopener">Course page <span aria-hidden="true">→</span></a>'
        cards.append(f'''<article class="course-card" data-course-card role="group" aria-label="Course {index}: {title}">
  <img class="course-card__image" src="{image}" alt="" loading="lazy" width="640" height="360">
  <div class="course-card__body">
    <h3 class="course-card__title">{title}</h3>
    <p class="course-card__description">{description}</p>
    <div class="course-card__metadata"><span>{semester}</span><span class="course-card__status course-card__status--{status}">{status}</span></div>
    <div class="course-card__actions">{public_action}<a class="course-card__action course-card__action--secondary" href="{admin}">Admin overview <span aria-hidden="true">→</span></a></div>
  </div>
</article>''')

    return f'''<div class="course-carousel" data-course-carousel aria-label="Course offerings">
  <div class="course-carousel__track" data-carousel-track tabindex="0">{"".join(cards)}</div>
  <div class="course-carousel__navigation" aria-label="Carousel navigation">
    <button class="course-carousel__button" type="button" data-carousel-previous aria-label="Previous course" disabled>←</button>
    <span class="course-carousel__hint">Scroll to explore all offerings</span>
    <button class="course-carousel__button" type="button" data-carousel-next aria-label="Next course">→</button>
  </div>
</div>'''


if __name__ == "__main__":
    print(current_upcoming_courses_markdown())
