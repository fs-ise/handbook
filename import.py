#!/usr/bin/env python3
import argparse
import os
from pathlib import Path
import re

BASE_URL_PREFIX = "https://digital-work-lab.github.io/handbook/docs/"
LOCAL_DOCS_ROOT = Path("/home/gerit/ownCloud/data/ub/handbook/docs")


def extract_front_matter_and_body(md_text: str):
    """Return (front_matter_text or None, body_text)."""
    # Match YAML front matter at the top: ---\n...\n---\n...
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", md_text, re.DOTALL)
    if m:
        front_matter = m.group(1)
        body = m.group(2)
        return front_matter, body
    else:
        return None, md_text


def extract_transition_fields(front_matter: str):
    """Extract transition_status and transition_comment from YAML-like text."""
    transition_status = None
    transition_comment = None

    if not front_matter:
        return transition_status, transition_comment

    # Very simple line-based extraction to avoid yaml dependency
    for line in front_matter.splitlines():
        stripped = line.strip()
        if stripped.startswith("transition_status:"):
            value = stripped.split(":", 1)[1].strip()
            transition_status = value.strip('\'"')
        elif stripped.startswith("transition_comment:"):
            value = stripped.split(":", 1)[1].strip()
            transition_comment = value.strip('\'"')

    return transition_status, transition_comment


def remove_first_johnny_decimal_heading(md_body: str) -> str:
    """
    In the imported markdown body, remove the first heading that matches e.g.
    '# 10.50 Travel' (i.e., a Johnny-decimal prefix).

    Only affects the first heading line that matches the Johnny-decimal pattern.
    """
    lines = md_body.splitlines()

    heading_pattern = re.compile(
        r"^(#{1,6}\s+)(\d{1,2}\.\d{2}(?:\.\d{2})?)\s+.*$"
    )

    for i, line in enumerate(lines):
        m = heading_pattern.match(line)
        if m:
            # Remove this heading line
            del lines[i]
            # Optionally remove following blank line for nicer spacing
            if i < len(lines) and lines[i].strip() == "":
                del lines[i]
            break

    return "\n".join(lines)


def integrate_transition_into_qmd_header(
    full_text: str,
    imported_transition_status: str | None,
    imported_transition_comment: str | None,
) -> str:
    """
    Take the full QMD text, integrate transition_status and transition_comment
    (from imported markdown) into the existing YAML header, and return new text.
    Other YAML fields from imported markdown are ignored.

    Ensures there is a blank line between the YAML header and the body.
    If the final transition_status == "toupdate", a Quarto callout-note using
    transition_comment is inserted at the top of the body (if not already present).
    Also replaces '{target=_blank}' with '{target=_blank}' in the body.
    """
    # Match QMD front matter at the top
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", full_text, re.DOTALL)
    if not m:
        # No YAML header found; nothing to integrate
        return full_text

    header_text = m.group(1)
    body_text = m.group(2)

    header_lines = []
    existing_status = None
    existing_comment = None

    # Read existing header, capture any existing transition_* values,
    # but do not keep the lines (we'll re-add final ones later).
    for line in header_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("transition_status:"):
            value = stripped.split(":", 1)[1].strip()
            existing_status = value.strip('\'"')
            continue
        if stripped.startswith("transition_comment:"):
            value = stripped.split(":", 1)[1].strip()
            existing_comment = value.strip('\'"')
            continue
        header_lines.append(line)

    # Decide final transition_* values: imported overrides existing
    final_status = imported_transition_status if imported_transition_status is not None else existing_status
    final_comment = imported_transition_comment if imported_transition_comment is not None else existing_comment

    # Append final transition fields if available
    if final_status is not None:
        header_lines.append(f'transition_status: "{final_status}"')
    if final_comment is not None:
        header_lines.append(f'transition_comment: "{final_comment}"')

    new_header_text = "\n".join(header_lines)

    # Prepare body: ensure exactly one blank line after the header
    body_text_stripped = body_text.lstrip("\n")

    # Replace Quarto link attribute syntax {target=_blank} -> {target=_blank}
    body_text_stripped = body_text_stripped.replace('{target=_blank}', '{target=_blank}')

    # If status == "toupdate", add a Quarto callout-note at the top (if not already there)
    if final_status == "toupdate" and final_comment:
        body_lines = body_text_stripped.splitlines()
        # Detect existing callout-note near top to avoid duplicates
        has_callout = any(
            re.match(r"^::: *callout-note", line.strip()) for line in body_lines[:10]
        )
        if not has_callout:
            callout = [
                "::: callout-note",
                f'This section is marked as "{final_status}": {final_comment}',
                ":::",
                "",
            ]
            body_text_stripped = "\n".join(callout + body_lines)

    new_full_text = f"---\n{new_header_text}\n---\n\n{body_text_stripped}"
    return new_full_text


def process_qmd_file(path: Path, dry_run: bool = False) -> None:
    """
    For a given .qmd file:
    - find lines like 'Import <url>' in the body
    - replace them with the contents (body only) of the mapped local markdown file
      (with the first Johnny-decimal heading removed entirely)
    - extract transition_status and transition_comment from the imported markdown
      YAML front matter and integrate them into the QMD YAML header
    - if transition_status == "toupdate", insert a Quarto callout-note with
      the transition_comment at the top of the body
    - replace '{target=_blank}' with '{target=_blank}' in the body
    - delete the markdown file afterwards
    """
    original_text = path.read_text(encoding="utf-8")

    # Match QMD front matter to separate header and body
    header_match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", original_text, re.DOTALL)
    if header_match:
        header_text = header_match.group(1)
        body_text = header_match.group(2)
    else:
        # Fallback if there is no YAML header
        header_text = None
        body_text = original_text

    # Track imported markdown files for later deletion
    imported_md_files: set[Path] = set()

    # Track transition fields discovered from imported markdown files
    imported_transition_status = None
    imported_transition_comment = None

    pattern = re.compile(r"^[ \t]*Import[ \t]+(https?://\S+)[ \t]*$", re.MULTILINE)

    def replace_import(match: re.Match) -> str:
        nonlocal imported_transition_status, imported_transition_comment

        url = match.group(1)

        if not url.startswith(BASE_URL_PREFIX):
            print(f"  [skip] URL not in handbook docs: {url}")
            return match.group(0)

        rel_html_path = url[len(BASE_URL_PREFIX) :]  # e.g. '10-lab/10_processes/10.60.department.html'
        # Convert .html to .md
        if "." in rel_html_path:
            base, _ext = os.path.splitext(rel_html_path)
            rel_md_path = base + ".md"
        else:
            # Fallback if no extension (unlikely)
            rel_md_path = rel_html_path + ".md"

        md_path = LOCAL_DOCS_ROOT / rel_md_path

        if not md_path.is_file():
            print(f"  [WARN] Markdown file not found for URL {url}")
            print(f"         Expected: {md_path}")
            return match.group(0)

        print(f"  [ok]  Importing {md_path} into {path}")
        imported_md_files.add(md_path)

        if dry_run:
            # In dry-run, keep the original line so nothing changes on disk
            return match.group(0)

        md_text = md_path.read_text(encoding="utf-8")
        front_matter, md_body = extract_front_matter_and_body(md_text)
        t_status, t_comment = extract_transition_fields(front_matter or "")

        # Prefer the most recent non-None values we encounter
        if t_status is not None:
            imported_transition_status = t_status
        if t_comment is not None:
            imported_transition_comment = t_comment

        # Remove the first Johnny-decimal heading entirely
        md_body = remove_first_johnny_decimal_heading(md_body)

        # Replace {target=_blank} in imported content as well (redundant but explicit)
        md_body = md_body.replace('{target=_blank}', '{target=_blank}')

        # Return only the body of the imported markdown (no YAML front matter)
        return md_body

    # Apply replacement only to the body text
    new_body_text = pattern.sub(replace_import, body_text)

    # Reassemble temporarily (header will be adjusted after integrating transitions)
    if header_text is not None:
        # Ensure a blank line after header when we reassemble
        temp_full_text = f"---\n{header_text}\n---\n\n{new_body_text.lstrip('\n')}"
    else:
        temp_full_text = new_body_text

    # Integrate transition_* fields into the QMD header and add callout if needed
    if not dry_run:
        final_text = integrate_transition_into_qmd_header(
            temp_full_text,
            imported_transition_status,
            imported_transition_comment,
        )
    else:
        final_text = original_text  # dry-run: no changes

    if final_text != original_text and not dry_run:
        path.write_text(final_text, encoding="utf-8")
        print(f"  [write] Updated {path}")
    elif final_text == original_text:
        print(f"[no change] {path}")

    # Delete imported markdown files (once per file) if not dry-run
    if not dry_run:
        for md_file in imported_md_files:
            try:
                md_file.unlink()
                print(f"  [delete] Removed {md_file}")
            except OSError as e:
                print(f"  [ERROR] Could not delete {md_file}: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Inline imported handbook markdown into .qmd files, "
            "integrate transition_status/transition_comment into the QMD YAML header, "
            "insert a Quarto callout-note when toupdate, "
            "replace '{: target=\"_blank\"}' with '{target=_blank}', "
            "and delete the original markdown files."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not modify or delete any files; just show what would happen.",
    )

    args = parser.parse_args()

    for qmd_root in ["management", "teaching", "research"]:

        if not Path(qmd_root).is_dir():
            print(f"[ERROR] qmd-root directory not found: {qmd_root}")
            continue

        print(f"Scanning for .qmd files under {qmd_root} (dry_run={args.dry_run})")
        qmd_files = sorted(Path(qmd_root).rglob("*.qmd"))

        if not qmd_files:
            print("No .qmd files found.")
            return

        for qmd_file in qmd_files:
            print(f"\nProcessing {qmd_file}")
            process_qmd_file(qmd_file, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
