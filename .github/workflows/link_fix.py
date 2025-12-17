from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable
import os

repo = os.getenv("GITHUB_REPOSITORY")  # e.g., "fs-ise/handbook"
sha = os.getenv("GITHUB_SHA")         # commit being checked
server = os.getenv("GITHUB_SERVER_URL", "https://github.com")


# Match inline markdown links:
#   [text](http...)
# optionally followed by an attribute block:
#   { ... }  (we will add/extend this form)
MARKDOWN_HTTP_LINK_PATTERN = re.compile(
    r"(\[([^\]]+)\]\((http[^\)]+)\))(\{[^}]*\})?"
)

# Match internal .html links:
#   [text](relative/path/file.html)
#   [text](/site/root/path/file.html)
HTML_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^h][^\)]+\.html)\)")


SKIP_URL_SUBSTRINGS = ("img.shields.io",)
SKIP_URL_SUFFIXES = (".png", ".svg")


def iter_content_files(root: Path) -> Iterable[Path]:
    """Yield .md and .qmd files (skip root-level files)."""
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix not in {".md", ".qmd"}:
            continue
        if len(p.relative_to(root).parts) == 1:
            continue
        yield p


def should_skip_external(url: str) -> bool:
    return any(s in url for s in SKIP_URL_SUBSTRINGS) or url.endswith(SKIP_URL_SUFFIXES)


def attrs_already_have_target_blank(attrs: str) -> bool:
    """
    True if the attribute block already sets target blank in either form:
      - target="_blank"
      - target=_blank
    """
    return bool(re.search(r'target\s*=\s*("_blank"|_blank)', attrs))


def normalize_to_brace_attrs(existing_attrs: str) -> str:
    """
    Convert an attribute block to the plain brace form:
      "{ ... }"
    If it's "{: ... }", drop the leading ":" while keeping the content.
    """
    inner = existing_attrs.strip()[1:-1].strip()  # remove outer braces
    if inner.startswith(":"):
        inner = inner[1:].strip()
    return inner


def append_target_blank_to_http_links(file_path: Path) -> bool:
    """Add {target=_blank} to http(s) links unless already present (any form)."""
    content = file_path.read_text(encoding="utf-8")

    def add_target_blank(match: re.Match) -> str:
        link = match.group(1)            # [text](url)
        url = match.group(3)             # url
        existing_attrs = match.group(4)  # {..} or {: ..} or None

        if should_skip_external(url):
            return match.group(0)

        if existing_attrs:
            if attrs_already_have_target_blank(existing_attrs):
                # Keep exactly as-is if it already has target blank
                return link + existing_attrs

            inner = normalize_to_brace_attrs(existing_attrs)
            if inner:
                return link + "{ " + inner + " target=_blank }"
            return link + "{ target=_blank }"

        return link + "{target=_blank}"

    updated = MARKDOWN_HTTP_LINK_PATTERN.sub(add_target_blank, content)

    if updated != content:
        file_path.write_text(updated, encoding="utf-8")
        print(f"Updated external links in {file_path}")
        return True

    print(f"No changes needed in {file_path}")
    return False


def candidates_for_quarto_source(file_path: Path, html_link: str, repo_root: Path) -> list[Path]:
    """
    Given a link to something.html, return plausible Quarto source candidates:
    - something.qmd / something.md
    - something/index.qmd / something/index.md  (pretty URLs)

    Handles:
    - relative links:  research/writing.html
    - site-root links: /research/writing.html   (Quarto absolute-to-site-root)
    """
    clean = html_link.split("#", 1)[0].split("?", 1)[0]
    rel_no_ext = clean[:-5]  # remove ".html"

    # Quarto site-root paths begin with "/". Don't let pathlib treat them
    # as OS-absolute paths; resolve them from repo_root instead.
    if rel_no_ext.startswith("/"):
        rel_no_ext = rel_no_ext.lstrip("/")
        base = repo_root / rel_no_ext
    else:
        base = file_path.parent / rel_no_ext

    return [
        Path(str(base) + ".qmd"),
        Path(str(base) + ".md"),
        base / "index.qmd",
        base / "index.md",
    ]


def check_internal_html_links(file_path: Path, repo_root: Path) -> list[tuple[str, list[Path]]]:
    """
    For each [..](..html) link, verify at least one plausible source exists.
    Returns list of (html_link, candidates) for broken ones.
    """
    content = file_path.read_text(encoding="utf-8")
    matches = HTML_LINK_PATTERN.findall(content)

    broken: list[tuple[str, list[Path]]] = []

    for _, html_link in matches:
        if html_link.startswith(("http://", "https://", "mailto:", "#")):
            continue
        if "_news" in html_link:
            continue

        cands = candidates_for_quarto_source(file_path, html_link, repo_root=repo_root)
        if not any(p.exists() for p in cands):
            broken.append((html_link, cands))

    return broken


def write_broken_links_report(
    broken: dict[Path, list[tuple[str, list[Path]]]],
    repo_root: Path,
) -> None:
    report_path = Path("broken_links.md")
    if not broken:
        if report_path.exists():
            report_path.unlink()
        print("No broken internal .html links found.")
        return

    edit_branch = os.getenv("GITHUB_EDIT_BRANCH", "revisions")

    with report_path.open("w", encoding="utf-8") as f:
        f.write("# Broken internal .html links\n\n")
        for src_file, items in sorted(broken.items(), key=lambda x: str(x[0])):
            rel = src_file.relative_to(repo_root).as_posix()

            if repo:
                # Direct link to GitHub's editor on the chosen branch
                edit_url = f"{server}/{repo}/edit/{edit_branch}/{rel}"
                f.write(f"## In [{rel}]({edit_url})\n\n")
            else:
                f.write(f"## In `{rel}`\n\n")

            for html_link, cands in items:
                f.write(f"- `{html_link}`\n")
                f.write("  - expected one of:\n")
                for c in cands:
                    try:
                        f.write(f"    - `{c.relative_to(repo_root)}`\n")
                    except ValueError:
                        f.write(f"    - `{c}`\n")
            f.write("\n")


def main() -> None:
    root = Path.cwd()

    # 1) Add {target=_blank} to external links in .md/.qmd (excluding root-level files)
    for fp in iter_content_files(root):
        append_target_blank_to_http_links(fp)

    # 2) Check internal .html links against plausible Quarto sources (.qmd/.md/index.*)
    broken: dict[Path, list[tuple[str, list[Path]]]] = {}
    for fp in iter_content_files(root):
        b = check_internal_html_links(fp, repo_root=root)
        if b:
            broken[fp] = b

    write_broken_links_report(broken, repo_root=root)


if __name__ == "__main__":
    main()
