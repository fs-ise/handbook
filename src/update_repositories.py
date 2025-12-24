import os
import json
import requests
from pathlib import Path
from datetime import datetime, timedelta

import yaml  # kept in case you later want to re-use paper.md parsing

ORG_NAMES = ["fs-ise", "digital-work-lab"]
BASE_URL = "https://api.github.com"
WORKFLOW_FILENAME = ".github/workflows/labot.yml"

cwd = Path.cwd()
OUTPUT_JSON = cwd / "assets" / "repos.json"

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    raise EnvironmentError("The GITHUB_TOKEN environment variable is not set or empty.")

HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    # needed to get topics from the repos API
    "Accept": "application/vnd.github.mercy-preview+json",
}


def get_workflow_id_by_filename(owner: str, repo_name: str, workflow_filename: str) -> int | None:
    """Gets the workflow ID for a specific workflow file in the repository."""
    url = f"{BASE_URL}/repos/{owner}/{repo_name}/actions/workflows"
    response = requests.get(url, headers=HEADERS)
    if response.status_code != 200:
        raise Exception(f"Error fetching workflows for {owner}/{repo_name}: {response.json()}")

    workflows = response.json().get("workflows", [])
    for workflow in workflows:
        if workflow.get("path", "").lower() == workflow_filename.lower():
            return workflow["id"]

    return None  # Workflow not found


def get_workflow_status(owner: str, repo_name: str, workflow_id: int | None) -> str:
    """Fetches the conclusion of the latest workflow run, or a sentinel if not found."""
    if workflow_id is None:
        return "not-found"

    url = f"{BASE_URL}/repos/{owner}/{repo_name}/actions/workflows/{workflow_id}/runs"
    response = requests.get(url, headers=HEADERS)
    if response.status_code != 200:
        raise Exception(f"Error fetching workflow runs for {owner}/{repo_name}: {response.json()}")

    runs = response.json().get("workflow_runs", [])
    if not runs:
        return "no-runs"

    latest_run = runs[0]
    conclusion = latest_run.get("conclusion") or "no-conclusion"
    return conclusion


def get_org_repositories(org_name: str) -> list[dict]:
    """Retrieve all repositories of the organization (paginated)."""
    url = f"{BASE_URL}/orgs/{org_name}/repos"
    repositories: list[dict] = []
    page = 1

    while True:
        response = requests.get(
            url,
            headers=HEADERS,
            params={"page": page, "per_page": 100},
        )
        if response.status_code != 200:
            raise Exception(f"Error fetching repositories for {org_name} (page {page}): {response.json()}")

        repos = response.json()
        if not repos:
            break

        repositories.extend(repos)
        page += 1

    return repositories


def get_repo_collaborators(owner: str, repo_name: str) -> list[str]:
    """Return a filtered list of collaborators for a repo."""
    url = f"{BASE_URL}/repos/{owner}/{repo_name}/collaborators"
    response = requests.get(url, headers=HEADERS)

    if response.status_code == 403:
        return ["Access Denied: Requires admin rights"]
    if response.status_code != 200:
        # silently ignore other errors for collaborators
        return []

    collaborators = []
    for collab in response.json():
        login = collab.get("login")
        if login not in ["geritwagner", "digital-work-labot"]:
            collaborators.append(login)
    return collaborators


def get_project_type(owner: str, repo_name: str) -> list[str]:
    """Infer project type(s) from files in the repository root."""
    repo_contents_url = f"{BASE_URL}/repos/{owner}/{repo_name}/contents"
    response = requests.get(repo_contents_url, headers=HEADERS)

    if response.status_code != 200:
        print(f"Error fetching repository contents for {owner}/{repo_name}: {response.json()}")
        return []

    contents = response.json()
    file_names = [content.get("name") for content in contents]
    p_types: list[str] = []

    if "paper.md" in file_names:
        p_types.append("paper")
    if "settings.json" in file_names and "status.yaml" in file_names:
        p_types.append("colrev")

    return p_types


def classify_area(topics: list[str]) -> str:
    """Classify a repository into research/teaching/other based on topics."""
    if "research" in topics:
        return "research"
    if "teaching-materials" in topics:
        return "teaching"
    return "other"


def main() -> None:
    six_months_ago = datetime.now() - timedelta(days=180)

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)

    result: list[dict] = []

    for org_name in ORG_NAMES:
        repos = get_org_repositories(org_name)

        for repo in repos:
            # Skip the GitHub Pages repo for this org (e.g., fs-ise/fs-ise.github.io)
            pages_repo_url = f"https://github.com/{org_name}/{org_name}.github.io"
            if repo["html_url"] == pages_repo_url:
                print(f"Skipping {repo['full_name']} (GitHub Pages repo)")
                continue

            print(f"Processing {repo['full_name']}...")

            topics = repo.get("topics") or []
            area = classify_area(topics)

            workflow_id = get_workflow_id_by_filename(org_name, repo["name"], WORKFLOW_FILENAME)
            labot_workflow_status = get_workflow_status(org_name, repo["name"], workflow_id)

            # Build base record
            repo_data: dict = {
                "owner": org_name,
                "name": repo["name"],
                "title": repo["name"],  # can be adapted later for display
                "html_url": repo["html_url"],
                "visibility": "Private" if repo.get("private") else "Public",
                "description": repo.get("description") or "",
                "area": area,
                "topics": topics,
                "created_at": repo.get("created_at"),
                "archived": repo.get("archived", False),
                "collaborators": get_repo_collaborators(org_name, repo["name"]),
                "updated_recently": datetime.strptime(
                    repo["pushed_at"], "%Y-%m-%dT%H:%M:%SZ"
                )
                > six_months_ago,
                "labot_workflow_status": labot_workflow_status,
                "project_type": get_project_type(org_name, repo["name"]),
            }

            # Paper classification tweak as before
            if "paper" in topics and "paper" not in repo_data["project_type"]:
                repo_data["project_type"].append("paper")

            # Determine where Labot is applicable
            if not (
                "paper" in repo_data["project_type"]
                or "teaching-materials" in topics
            ):
                repo_data["labot_workflow_status"] = "not-applicable"

            result.append(repo_data)

    # Write everything to assets/repos.json
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, sort_keys=True, ensure_ascii=False)

    print(f"Wrote {len(result)} repository records to {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
