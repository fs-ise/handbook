from pathlib import Path
import re
import textwrap

import colrev.loader.load_utils
from pathlib import Path
import csv

import colrev.loader.load_utils

# ---------------------------------------------------------
# Input: your talks as BibTeX (CoLRev) records
# ---------------------------------------------------------
BIB_PATH = Path("assets/talks.bib")
OUTPUT_DIR = Path("research/talks")
CSV_PATH = Path("talk_places.csv")


def create_places_csv() -> None:
    records = colrev.loader.load_utils.load(filename=str(BIB_PATH))

    # Define the CSV columns you want
    fieldnames = [
        "id",
        "title",
        "venue",
        "location",
        "date",
        "latitude",
        "longitude",
    ]

    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for rec_id, rec in records.items():
            # only export records that have coordinates
            if "latitude" not in rec or "longitude" not in rec:
                continue

            row = {
                "id": rec_id,
                "title": rec.get("title", ""),
                "venue": rec.get("venue", ""),
                "location": rec.get("location", ""),
                "date": rec.get("date", ""),
                "latitude": rec.get("latitude", ""),
                "longitude": rec.get("longitude", ""),
            }
            writer.writerow(row)

    print(f"Wrote {CSV_PATH}")


def load_talks_from_bib(filename: Path):
    """Load talk-like records from a BibTeX file via CoLRev."""
    records = colrev.loader.load_utils.load(filename=filename)

    talks: list[dict] = []
    for rec_id, rec in records.items():
        # CoLRev / BibTeX fields
        title = (rec.get("title") or "").strip("{}")
        eventtitle = rec.get("eventtitle")
        venue = rec.get("venue") or eventtitle
        location = rec.get("location")
        date = rec.get("date")  # e.g., 2015-12-15
        url = rec.get("url")
        howpublished = rec.get("howpublished") or rec.get("note")
        paper_key = rec.get("paper_key")

        talk = {
            "id": rec_id,
            "title": title,
            "venue": venue,
            "location": location,
            "date": date,
            "slides_url": url,
            "howpublished": howpublished,
            "paper_key": paper_key,
        }
        talks.append(talk)

    return talks


def slug_from_title(title: str, date: str | None = None) -> str:
    """Fallback slug from title and (optional) date."""
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    if date:
        date_prefix = date.replace("-", "_")
        slug = f"{date_prefix}_{slug}" if slug else date_prefix
    return slug or "talk"


def choose_slug(talk: dict) -> str:
    """
    Prefer using information from the slides link, so filenames get a date prefix:

    - If slides url is like '2024_10_22_inaugural_lecture/slides.html',
      use '2024_10_22_inaugural_lecture'.
    - If slides url is like '2024_10_22_inaugural_lecture_digital_knowledge_work.pdf',
      use the filename stem '2024_10_22_inaugural_lecture_digital_knowledge_work'.

    Otherwise fall back to a slug derived from date + title.
    """
    url = talk.get("slides_url")
    if url:
        # Case 1: directory-based path – keep first component
        if "/" in url:
            first = url.split("/", 1)[0]
            if first:
                return first
        # Case 2: flat file – use stem (which already includes the date prefix)
        stem = Path(url).stem
        if stem:
            return stem

    return slug_from_title(talk["title"], talk.get("date"))


def build_qmd(talk: dict) -> str:
    venue = talk.get("venue")
    location = talk.get("location")
    date = talk.get("date")
    howpublished = talk.get("howpublished", "NA")
    slides_url = talk.get("slides_url")
    bibtex_id = talk.get("id")
    paper_key = talk.get("paper_key")

    # Materials list (for now, only slides)
    materials = []
    if slides_url:
        materials.append(f"- [Slides]({slides_url})")

    # If there is a related paper, link to ../papers/{paper_key}.html
    if paper_key:
        materials.append(f"- [Paper](../papers/{paper_key}.html)")

    materials_block = "\n".join(materials) if materials else "_No materials linked._"

    # Simple helper to escape double quotes for YAML
    def _esc(val: str | None) -> str | None:
        if val is None:
            return None
        return val.replace('"', '\\"')

    meta_lines = [
        "---",
        f'title: "{_esc(talk["title"])}"',
    ]
    if date:
        meta_lines.append(f'date: "{_esc(date)}"')
    if location:
        meta_lines.append(f'location: "{_esc(location)}"')
    if venue:
        meta_lines.append(f'venue: "{_esc(venue)}"')
    if bibtex_id:
        meta_lines.append(f'bibtex_id: "{_esc(bibtex_id)}"')
    if howpublished:
        meta_lines.append(f'howpublished: "{_esc(howpublished)}"')
    if paper_key:
        meta_lines.append(f'paper_key: "{_esc(paper_key)}"')
    meta_lines.append("format: html")
    meta_lines.append("---")

    header = "\n".join(meta_lines)

    info_lines = []
    if venue:
        # show meta-field venue so you can change it in YAML and keep it in sync
        info_lines.append(f"- **Venue:** {{{{< meta venue >}}}}")
    if location:
        info_lines.append(f"- **Location:** {{{{< meta location >}}}}")
    if date:
        info_lines.append(f"- **Date:** {{{{< meta date >}}}}")
    if howpublished:
        info_lines.append(f"- **Type:** {{{{< meta howpublished >}}}}")

    info_block = "\n".join(info_lines) if info_lines else "_Details not available._"

    # Optional related paper block (visible text, not commented out)
    related_block = ""
    if paper_key:
        related_block = f"\n\n**Related paper:** [Link](../papers/{paper_key}.html)\n"

    # Slides embed (only if we have a PDF-like URL)
    if slides_url and slides_url.lower().endswith(".pdf"):
        slides_embed = textwrap.dedent(
            f"""\
            ```{{=html}}
            <embed src="{slides_url}"
                   type="application/pdf"
                   width="100%"
                   height="600px" />
            ```
            """
        )
    else:
        slides_embed = "_Slides not available as embedded PDF._"

    body = textwrap.dedent(
        f"""## Talk information

{info_block}{related_block}

::: {{.callout-note}}

Slides coming soon...

:::

## Materials

{materials_block}

"""
        # If you later want to show the embed again, you can re-enable this:
        # f"## Slides\n\n{slides_embed}\n"
    )

    return header + "\n\n" + body.strip() + "\n"


def main():
    talks = load_talks_from_bib(BIB_PATH)
    OUTPUT_DIR.mkdir(exist_ok=True)

    for talk in talks:
        slug = choose_slug(talk)
        qmd_path = OUTPUT_DIR / f"{slug}.qmd"
        content = build_qmd(talk)
        qmd_path.write_text(content, encoding="utf-8")
        print(f"Written: {qmd_path}")


if __name__ == "__main__":
    main()
    create_places_csv()
