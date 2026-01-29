#!/usr/bin/env python3
from __future__ import annotations

import os
from datetime import datetime, timezone

from github import Github


ISSUE_TITLE = "Monthly: check handbook data + research streams updates"
ASSIGNEE = "geritwagner"

HANDBOOK_DATA_URL = "https://github.com/fs-ise/handbook/tree/main/data"
RESEARCH_STREAMS_URL = "https://fs-ise.github.io/handbook/research/statement.html"


def _now_utc_monthstamp() -> str:
    # e.g., "2026-01"
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _comment_body() -> str:
    month = _now_utc_monthstamp()
    run_id = os.getenv("GITHUB_RUN_ID", "")
    repo = os.getenv("GITHUB_REPOSITORY", "")

    run_hint = f"\n\n_Run: {repo} (run id: {run_id})_" if (run_id and repo) else ""

    return (
        f"@{ASSIGNEE} monthly check-in ({month}):\n\n"
        "Could you please confirm whether there is anything to update?\n\n"
        f"- Handbook data files: {HANDBOOK_DATA_URL}\n"
        f"- Papers to add / update in research streams: {RESEARCH_STREAMS_URL}\n\n"
        "If yes, please drop notes/links here (or open a PR). Thanks!"
        f"{run_hint}"
    )


def _issue_body() -> str:
    return (
        "This is a rolling issue used by the monthly automation.\n\n"
        "Each month it will post a comment mentioning the maintainer, asking whether:\n"
        f"- anything in `{HANDBOOK_DATA_URL}` needs updating, and\n"
        f"- any papers should be added to the research streams page: {RESEARCH_STREAMS_URL}\n\n"
        "Feel free to keep this issue open permanently."
    )


def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("Missing env var GITHUB_TOKEN")

    repo_full = os.environ.get("GITHUB_REPOSITORY")
    if not repo_full:
        raise SystemExit("Missing env var GITHUB_REPOSITORY (expected owner/repo)")

    gh = Github(token)
    repo = gh.get_repo(repo_full)

    # Find existing open issue with matching title
    target_issue = None
    for issue in repo.get_issues(state="open"):
        if issue.title.strip() == ISSUE_TITLE:
            target_issue = issue
            break

    if target_issue is None:
        # If none open, see if there's a closed one to re-open (keeps history in one place)
        for issue in repo.get_issues(state="closed"):
            if issue.title.strip() == ISSUE_TITLE:
                target_issue = issue
                target_issue.edit(state="open")
                break

    if target_issue is None:
        target_issue = repo.create_issue(
            title=ISSUE_TITLE,
            body=_issue_body(),
            assignees=[ASSIGNEE],
        )

    # Add a monthly comment (always)
    target_issue.create_comment(_comment_body())


if __name__ == "__main__":
    main()
