#!/usr/bin/env python3
"""
Generate Quarto .qmd paper files from a records.bib file using CoLRev.

- Reads records.bib from the current working directory
- Removes all existing files in research/papers before generation
- For each record, creates research/papers/<ID>.qmd
- If research/papers/<ID>.qmd already exists (after cleanup), it is skipped
- The Summary section is based on the record's abstract field
- If fulltext_oa is present, adds a Bootstrap button linking to the PDF
  (URL or repo-root-relative path; label depends on oa_status)
- If there is a DOI/URL, adds a link button (with icon) before the PDF button
- If author_copy_url exists, adds an author-copy button
- If summary_url / appendix_url / dataset_url / dataset_doi / code_url are present,
  adds an “Additional resources” section with links
- Appends APA-style citation (with hanging indent), and BibTeX + RIS blocks for copy-paste.

Requirements:
    pip install colrev
"""

from __future__ import annotations

import json
import html
import shutil
from pathlib import Path
from typing import List, Iterable, Dict, Any

import colrev.loader.load_utils as load_utils


RECORDS_BIB = Path("/home/gerit/ownCloud/data/publications/my-papers-colrev/data/records.bib")
OUTPUT_DIR = Path("research/papers")


DEFAULT_BODY_TEMPLATE = """"""


# ----------------------------------------------------------------------
# Helpers for citations (BibTeX, RIS, APA)
# ----------------------------------------------------------------------


def yaml_escape(value: str) -> str:
    """Escape double quotes for safe inclusion in YAML."""
    if value is None:
        return ""
    return str(value).replace('"', '\\"')


def record_to_bibtex(rec: dict) -> str:
    """Reconstruct a BibTeX entry from a record dict."""
    entrytype = rec.get("ENTRYTYPE", "article")
    key = rec.get("ID") or rec.get("citation_key") or rec.get("colrev_id")

    if not key:
        raise ValueError("Record is missing a citation key (ID / citation_key / colrev_id).")

    field_lines: List[str] = []
    max_field_len = 10
    for field, value in rec.items():
        if field in {
            "ENTRYTYPE",
            "ID",
            "citation_key",
            "colrev_id",
            "colrev_origin",
            "colrev_pdf_id",
            "screening_criteria",
            "file",
            "oa_status",
            "fulltext_oa",
            "colrev_status",
            "colrev_masterdata_provenance",
            "colrev_data_provenance",
            "colrev.dblp.dblp_key",
            "curation_id",
            "language",
            "dblp_key",
            "topic",
            "lr_type_pare_et_al",
            "goal_rowe",
            "synthesis",
            "r_gaps",
            "theory_building",
            "aggregating_evidence",
            "r_agenda",
            "r_agenda_levels",
            "cited_by",
            "keywords",
            "colrev.europe_pmc.europe_pmc_id",
            # additional machine-useful / custom fields we *don't* want in BibTeX
            "summary_url",
            "appendix_url",
            "dataset_url",
            "dataset_doi",
            "code_url",
            "author_copy_url",
        }:
            continue
        if value is None or value == "":
            continue

        v = str(value).replace("\n", " ").strip()
        field_lines.append(f"  {field:<{max_field_len}} = {{{v}}},")

    if field_lines:
        field_lines[-1] = field_lines[-1].rstrip(",")

    lines = [f"@{entrytype}{{{key},"] + field_lines + ["}"]
    return "\n".join(lines)


def record_to_ris(rec: dict) -> str:
    """Convert a record dict to a single RIS entry."""
    entrytype = str(rec.get("ENTRYTYPE", "article")).lower()
    type_map = {
        "article": "JOUR",
        "inproceedings": "CONF",
        "proceedings": "CONF",
        "conference": "CONF",
        "book": "BOOK",
        "phdthesis": "THES",
        "mastersthesis": "THES",
        "techreport": "RPRT",
    }
    ris_type = type_map.get(entrytype, "GEN")

    lines = [f"TY  - {ris_type}"]

    # Authors
    authors = str(rec.get("author", "")).strip()
    if authors:
        for a in authors.split(" and "):
            a = a.strip()
            if a:
                lines.append(f"AU  - {a}")

    # Title
    if rec.get("title"):
        lines.append(f"TI  - {rec['title']}")

    # Journal / booktitle
    outlet = rec.get("journal") or rec.get("booktitle")
    if outlet:
        lines.append(f"T2  - {outlet}")

    # Year
    year = str(rec.get("year", "")).strip()
    if year:
        lines.append(f"PY  - {year}")

    # Volume / issue / pages
    if rec.get("volume"):
        lines.append(f"VL  - {rec['volume']}")
    if rec.get("number"):
        lines.append(f"IS  - {rec['number']}")
    if rec.get("pages"):
        pages = str(rec["pages"])
        if "--" in pages:
            sp, ep = pages.split("--", 1)
            lines.append(f"SP  - {sp.strip()}")
            lines.append(f"EP  - {ep.strip()}")
        else:
            lines.append(f"SP  - {pages.strip()}")

    # DOI
    if rec.get("doi"):
        lines.append(f"DO  - {rec['doi']}")

    # URL (if present)
    if rec.get("url"):
        lines.append(f"UR  - {rec['url']}")

    # End of record
    lines.append("ER  - ")
    return "\n".join(lines)


def _format_author_name_for_apa(author: str) -> str:
    """
    Convert 'Last, First Middle' to 'Last, F. M.' (very simple heuristic).
    """
    author = author.strip()
    if not author:
        return ""

    if "," in author:
        last, given = author.split(",", 1)
        last = last.strip()
        given_parts = [p for p in given.strip().split() if p]
    else:
        # assume 'First Middle Last'
        parts = [p for p in author.split() if p]
        if len(parts) == 1:
            return parts[0]
        last = parts[-1]
        given_parts = parts[:-1]

    initials = " ".join(f"{p[0]}." for p in given_parts if p)
    if initials:
        return f"{last}, {initials}"
    return last


def _format_authors_apa(authors_raw: str) -> str:
    """Format an 'author' field (BibTeX style) into APA-style author list."""
    if not authors_raw:
        return ""

    authors = [a.strip() for a in authors_raw.split(" and ") if a.strip()]
    formatted = [_format_author_name_for_apa(a) for a in authors if a]

    if not formatted:
        return ""

    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]} & {formatted[1]}"
    # 3+ authors
    return ", ".join(formatted[:-1]) + f", & {formatted[-1]}"


def format_apa_citation(rec: dict) -> str:
    """
    Create a simple APA-style citation string from a record dict.

    Example shape:
    Author, A. A., & Author, B. B. (2020). Title of the article.
    Journal Name, 10(2), 123–145. https://doi.org/xxx
    """
    authors_raw = str(rec.get("author", "")).strip()
    authors_str = _format_authors_apa(authors_raw)

    year = str(rec.get("year", "")).strip()
    if year:
        year_str = f"({year})."
    else:
        year_str = "(n.d.)."

    title = str(rec.get("title", "")).strip()

    journal = str(rec.get("journal", "")).strip()
    booktitle = str(rec.get("booktitle", "")).strip()
    outlet = journal or booktitle

    volume = str(rec.get("volume", "")).strip()
    number = str(rec.get("number", "")).strip()
    pages = str(rec.get("pages", "")).strip()

    # Build outlet part
    outlet_parts: List[str] = []
    if outlet:
        outlet_parts.append(f"*{outlet}*")

    vol_issue_pages = ""
    if volume:
        vol_issue_pages += volume
    if number:
        vol_issue_pages += f"({number})"
    if pages:
        if vol_issue_pages:
            vol_issue_pages += f", {pages}"
        else:
            vol_issue_pages = pages

    if vol_issue_pages:
        outlet_parts.append(vol_issue_pages)

    outlet_str = ""
    if outlet_parts:
        outlet_str = " ".join(outlet_parts) + "."

    # DOI / URL
    doi_raw = str(rec.get("doi", "")).strip()
    if doi_raw and not doi_raw.startswith("http"):
        doi = f"https://doi.org/{doi_raw}"
    else:
        doi = doi_raw

    url = str(rec.get("url", "")).strip()

    link_str = ""
    if doi:
        link_str = doi
    elif url:
        link_str = url

    parts: List[str] = []
    if authors_str:
        parts.append(authors_str)
    parts.append(year_str)
    if title:
        parts.append(f"{title}.")
    if outlet_str:
        parts.append(outlet_str)
    if link_str:
        parts.append(link_str)

    return " ".join(p for p in parts if p).strip()


# ----------------------------------------------------------------------
# Original helpers
# ----------------------------------------------------------------------


def load_records(path: Path) -> Iterable[Dict[str, Any]]:
    """Load records via CoLRev's loader and normalize to an iterable of dicts."""
    if not path.is_file():
        raise FileNotFoundError(f"Records file not found: {path}")

    records = load_utils.load(filename=str(path))

    # CoLRev may return a dict of records or a list-like – handle both
    if isinstance(records, dict):
        # Common pattern: {ID: record_dict, ...}
        return records.values()
    elif isinstance(records, (list, tuple)):
        return records
    else:
        raise TypeError(
            f"Unexpected records type from load_utils.load(): {type(records)}"
        )


def load_body_template() -> str:
    """Return a default template."""
    return DEFAULT_BODY_TEMPLATE


def split_keywords(raw: str) -> List[str]:
    """Split a raw keywords string into a list (splitting on ';' or ',')."""
    if not raw:
        return []
    tmp = raw.replace(";", ",")
    parts = [p.strip() for p in tmp.split(",")]
    return [p for p in parts if p]


def get_field(record: Dict[str, Any], *names: str, default: str = "") -> str:
    """Try multiple field names on a record, return first non-empty as string."""
    for n in names:
        if n in record and record[n]:
            return str(record[n])
    return default


def build_yaml_header(record: Dict[str, Any]) -> str:
    """
    Build a YAML header string from a CoLRev record.

    - title: from 'title'
    - date: from 'year'
    - date-format: 'YYYY'
    - categories: based on keywords (fallback to ['research-paper'])
    - keywords: from 'keywords'
    - doi: from 'doi'
    - url: from 'url'
    - journal.name: from 'journal' / 'journal.name'
    - outlet: from 'outlet' / 'journal' / 'booktitle'
    - author: from 'author'
    - citation_key: from 'ID'
    """
    title = get_field(record, "title").strip()
    year = get_field(record, "year").strip()

    raw_keywords = get_field(record, "keywords", default="")
    keywords = split_keywords(raw_keywords)

    # categories based on keywords, fallback
    categories = keywords if keywords else ["research-paper"]

    doi = get_field(record, "doi", default="").strip()
    url = get_field(record, "url", default="").strip()

    # new fields
    journal_name = get_field(record, "journal", "journal.name", default="").strip()
    outlet = get_field(record, "outlet", "journal", "booktitle", default="").strip()
    author = get_field(record, "author", default="").strip()

    yaml_lines = ["---"]

    if title:
        yaml_lines.append(f"title: {json.dumps(title)}")
    else:
        yaml_lines.append('title: ""  # TODO: add title')

    if year:
        yaml_lines.append(f"date: {json.dumps(year)}")
    else:
        yaml_lines.append('date: ""  # TODO: add year')
    yaml_lines.append('date-format: "YYYY"')

    yaml_lines.append(f"categories: {json.dumps(categories)}")
    yaml_lines.append(f"keywords: {json.dumps(keywords)}")

    if doi:
        yaml_lines.append(f"doi: {json.dumps(doi)}")
    if url:
        yaml_lines.append(f"url: {json.dumps(url)}")
    if journal_name:
        yaml_lines.append(f"journal.name: {json.dumps(journal_name)}")
    if outlet:
        yaml_lines.append(f"outlet: {json.dumps(outlet)}")
    if author:
        yaml_lines.append(f"author: {json.dumps(author)}")

    key = get_field(record, "ID", "id", default="")
    if key:
        yaml_lines.append(f"citation_key: {json.dumps(key)}")

    yaml_lines.append("---")
    yaml_lines.append("")  # blank line before body

    return "\n".join(yaml_lines)


def build_body(record: Dict[str, Any], template_body: str) -> str:
    """
    Build the .qmd body content:

    - Adds a # Summary section based on the abstract field
    - If there is a DOI/URL, adds a link button (with icon)
    - If author_copy_url exists, adds an author-copy button
    - If fulltext_oa is present, adds a Bootstrap button with a PDF icon
      linking to the PDF (URL or repo-root-relative path)
      - Label is 'Open access PDF' if oa_status == 'open'
      - Otherwise, label is 'Full-text PDF'
    - Buttons are centered and shown on the same line
    - If summary_url / appendix_url / dataset_url / dataset_doi / code_url are present,
      adds a “## Additional resources” section with links
    - Then appends the template body (with an initial '# Summary' removed if present)
    - Then appends APA-style citation (with hanging indent), BibTeX, and RIS sections.
    """
    abstract = get_field(record, "abstract", default="").strip()

    # Link button from DOI/URL (landing page)
    doi_raw = get_field(record, "doi", default="").strip()
    url_raw = get_field(record, "url", default="").strip()

    landing_link = ""
    if doi_raw and not doi_raw.startswith("http"):
        landing_link = f"https://doi.org/{doi_raw}"
    elif doi_raw:
        landing_link = doi_raw
    elif url_raw:
        landing_link = url_raw

    # Author copy button (e.g., preprint / postprint)
    author_copy_url = get_field(record, "author_copy_url", default="").strip()

    # OA status and full text PDF
    oa_status = get_field(record, "oa_status", default="").strip().lower()
    fulltext_oa_raw = get_field(record, "fulltext_oa", default="").strip()

    fulltext_oa_href = ""
    if fulltext_oa_raw:
        if fulltext_oa_raw.startswith("http"):
            fulltext_oa_href = fulltext_oa_raw
        elif fulltext_oa_raw == "TODO":
            pass
        else:
            # Treat as repo-root-relative path, so it works from /research/papers/...
            fulltext_oa_href = "/" + fulltext_oa_raw.lstrip("/")

    if oa_status == "open":
        fulltext_label = "Open access PDF"
    else:
        fulltext_label = "Full-text PDF"

    # Build a single centered button bar
    buttons_block = ""
    if landing_link or author_copy_url or fulltext_oa_href:
        btns: List[str] = []

        if landing_link:
            btns.append(
                f'  <a class="btn btn-sm btn-outline-secondary me-2" href="{landing_link}" '
                'target="_blank" role="button">\n'
                '    <i class="bi bi-box-arrow-up-right"></i> Article / DOI link\n'
                "  </a>"
            )

        if author_copy_url:
            btns.append(
                f'  <a class="btn btn-sm btn-outline-secondary me-2" href="{author_copy_url}" '
                'target="_blank" role="button">\n'
                '    <i class="bi bi-file-earmark-text"></i> Author copy\n'
                "  </a>"
            )

        if fulltext_oa_href:
            btns.append(
                f'  <a class="btn btn-sm btn-outline-primary" href="{fulltext_oa_href}" '
                'target="_blank" role="button">\n'
                '    <i class="bi bi-file-earmark-pdf"></i> '
                f"{fulltext_label}\n"
                "  </a>"
            )

        buttons_block = (
            '<div class="text-center my-3">\n'
            + "\n".join(btns)
            + "\n</div>\n"
        )

    parts: List[str] = []

    # Summary from abstract + optional buttons
    summary_text = abstract if abstract else "Short abstract…"
    summary_block = f"\n\n# Summary\n\n{summary_text}\n"
    if buttons_block:
        summary_block += "\n" + buttons_block + "\n"

    parts.append(summary_block)

    # --- Additional resources --------------------------------------------
    summary_url = get_field(record, "summary_url", default="").strip()
    appendix_url = get_field(record, "appendix_url", default="").strip()
    dataset_url = get_field(record, "dataset_url", default="").strip()
    dataset_doi_raw = get_field(record, "dataset_doi", default="").strip()
    code_url = get_field(record, "code_url", default="").strip()

    dataset_doi_link = ""
    if dataset_doi_raw:
        if dataset_doi_raw.startswith("http"):
            dataset_doi_link = dataset_doi_raw
        else:
            dataset_doi_link = f"https://doi.org/{dataset_doi_raw}"

    resource_lines: List[str] = []
    if summary_url:
        resource_lines.append(f"- Summary / overview: <{summary_url}>")
    if appendix_url:
        resource_lines.append(f"- Appendix / supplementary materials: <{appendix_url}>")
    if code_url:
        resource_lines.append(f"- Code / source: <{code_url}>")
    if dataset_url and dataset_doi_link:
        resource_lines.append(
            f"- Dataset: <{dataset_url}> (DOI: <{dataset_doi_link}>)"
        )
    elif dataset_url:
        resource_lines.append(f"- Dataset: <{dataset_url}>")
    elif dataset_doi_link:
        resource_lines.append(f"- Dataset DOI: <{dataset_doi_link}>")

    if resource_lines:
        resources_block = "## Additional resources\n\n" + "\n".join(resource_lines) + "\n"
        parts.append(resources_block)

    # Avoid duplicated '# Summary' if the template already has one at the top
    tmpl = template_body.lstrip()
    if tmpl.lower().startswith("# summary"):
        tmpl_lines = tmpl.splitlines()
        i = 1  # skip the '# Summary' line
        while i < len(tmpl_lines) and tmpl_lines[i].strip() == "":
            i += 1
        tmpl = "\n".join(tmpl_lines[i:]).lstrip("\n")

    if tmpl.strip():
        parts.append(tmpl)

    # --- Citation sections -------------------------------------------------
    apa_citation = format_apa_citation(record).strip()
    if apa_citation:
        escaped_citation = html.escape(apa_citation)
        parts.append(
            "## Citation (APA style)\n\n"
            '<div class="apa-citation">\n'
            '<p style="text-indent:-2.5em; margin-left:2.5em;">\n'
            f"{escaped_citation}\n"
            "</p>\n"
            "</div>\n"
        )

    bibtex_entry = record_to_bibtex(record)
    if bibtex_entry.strip():
        parts.append(
            "## Citation: BibTeX\n\n"
            "```bibtex\n"
            f"{bibtex_entry}\n"
            "```\n"
        )

    ris_entry = record_to_ris(record)
    if ris_entry.strip():
        parts.append(
            "## Citation: RIS\n\n"
            "```bibtex\n"
            f"{ris_entry}\n"
            "```\n"
        )

    return "\n\n".join(parts).rstrip() + "\n"


def main():
    records_iter = load_records(RECORDS_BIB)

    # Ensure output dir exists and is empty before generation
    if OUTPUT_DIR.exists():
        # Remove all files and subdirectories in research/papers
        for child in OUTPUT_DIR.iterdir():
            if child.is_file():
                child.unlink()
            else:
                shutil.rmtree(child)
    else:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # (Re)ensure directory exists (after potential deletion of subdirs)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    template_body = load_body_template()

    created = 0
    skipped = 0

    for record in records_iter:
        # CoLRev records are usually dict-like
        # Ensure we have a mutable dict (in case CoLRev returns a custom type)
        record = dict(record)

        key = get_field(record, "ID", "id", default="").strip()
        if not key:
            print("Warning: skipping record without ID:", record)
            continue

        # Ensure the record has ID for BibTeX/RIS generation
        record.setdefault("ID", key)

        out_path = OUTPUT_DIR / f"{key}.qmd"

        if out_path.exists():
            print(f"Skipping existing file: {out_path}")
            skipped += 1
            continue

        yaml_header = build_yaml_header(record)
        body = build_body(record, template_body)
        content = yaml_header + body

        out_path.write_text(content, encoding="utf8")
        print(f"Created {out_path}")
        created += 1

    print(f"\nDone. Created {created} file(s), skipped {skipped} existing file(s).")


if __name__ == "__main__":
    main()
