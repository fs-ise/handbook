"""Generate a repository conformance report for teaching repositories.

The checker discovers repositories from course-page YAML front matter and writes a
static JSON report plus a Quarto fragment. It intentionally does not run during
Quarto rendering.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import yaml

STATUSES = ("pass", "warning", "fail", "not_applicable", "not_checked", "error")
STATUS_LABELS = {
    "pass": "✅ Pass",
    "warning": "⚠️ Warning",
    "fail": "❌ Fail",
    "not_applicable": "➖ Not applicable",
    "not_checked": "❔ Not checked",
    "error": "🛑 Error",
}


@dataclass(frozen=True)
class Repository:
    course_id: str
    course: str
    repository: str
    repository_url: str
    repository_type: str
    source_path: str


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    label: str
    status: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RepositoryContext:
    metadata: Repository
    path: Path | None
    commit: str | None
    github_metadata: dict[str, Any] | None = None
    branch_protection: dict[str, Any] | None = None


def handbook_root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_front_matter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        return {}
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def normalize_github_repository(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    value = value.strip().strip("'").strip('"')
    match = re.search(r"github\.com[:/](?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)", value)
    if not match:
        return None
    owner = match.group("owner")
    repo = match.group("repo").removesuffix(".git")
    return f"{owner}/{repo}", f"https://github.com/{owner}/{repo}"


def discover_repositories(course_pages_dir: Path) -> list[Repository]:
    repositories: list[Repository] = []
    seen: set[str] = set()
    for path in sorted([*course_pages_dir.glob("*.md"), *course_pages_dir.glob("*.qmd")]):
        meta = read_front_matter(path)
        course_id = str(meta.get("title_short") or path.stem).strip()
        course = str(meta.get("title") or course_id).strip()
        candidates = [("materials", meta.get("repository"))]
        for key in ("exams_repository", "exam_repository", "repository_exams", "exams"):
            candidates.append(("exams", meta.get(key)))
        for repository_type, raw_url in candidates:
            normalized = normalize_github_repository(raw_url)
            if normalized is None:
                continue
            full_name, url = normalized
            if full_name in seen:
                continue
            seen.add(full_name)
            repositories.append(
                Repository(course_id, course, full_name, url, repository_type, str(path.resolve().relative_to(handbook_root())))
            )
    return repositories


def run_git(args: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, check=check)


def clone_dir_name(repository: str) -> str:
    return repository.replace("/", "__")


def resolve_repository(repo: Repository, workspace: Path | None, cache_dir: Path, offline: bool) -> tuple[Path | None, str | None, list[str]]:
    errors: list[str] = []
    candidates: list[Path] = []
    if workspace:
        candidates.extend([workspace / repo.repository.split("/", 1)[1], workspace / clone_dir_name(repo.repository)])
    for candidate in candidates:
        if (candidate / ".git").exists():
            path = candidate
            break
    else:
        path = cache_dir / clone_dir_name(repo.repository)
        if not (path / ".git").exists():
            if offline:
                return None, None, ["No local clone found and --offline prevents cloning."]
            cache_dir.mkdir(parents=True, exist_ok=True)
            proc = run_git(["clone", repo.repository_url + ".git", str(path)], check=False)
            if proc.returncode != 0:
                return None, None, [proc.stderr.strip() or proc.stdout.strip()]
    if not offline:
        proc = run_git(["fetch", "--prune"], cwd=path, check=False)
        if proc.returncode != 0:
            errors.append(proc.stderr.strip() or "git fetch failed")
        else:
            run_git(["pull", "--ff-only"], cwd=path, check=False)
    commit_proc = run_git(["rev-parse", "HEAD"], cwd=path, check=False)
    commit = commit_proc.stdout.strip() if commit_proc.returncode == 0 else None
    return path, commit, errors


def result(check_id: str, label: str, status: str, message: str, **evidence: Any) -> CheckResult:
    return CheckResult(check_id, label, status, message, {k: v for k, v in evidence.items() if v is not None})


def check_accessible(ctx: RepositoryContext) -> CheckResult:
    if ctx.path and ctx.path.exists():
        return result("repository.accessible", "Repository can be accessed", "pass", "Repository clone is available", path=str(ctx.path))
    return result("repository.accessible", "Repository can be accessed", "error", "Repository could not be cloned or opened")


def file_exists(ctx: RepositoryContext, filename: str, check_id: str, label: str) -> CheckResult:
    if not ctx.path:
        return result(check_id, label, "not_checked", "Repository is not available")
    path = ctx.path / filename
    return result(check_id, label, "pass" if path.exists() else "fail", f"{'Found' if path.exists() else 'Missing'} {filename}", path=filename)


def check_readme(ctx: RepositoryContext) -> CheckResult: return file_exists(ctx, "README.md", "files.readme", "README is available")
def check_makefile(ctx: RepositoryContext) -> CheckResult: return file_exists(ctx, "Makefile", "files.makefile", "Makefile is available")
def check_references(ctx: RepositoryContext) -> CheckResult: return file_exists(ctx, "references.bib", "files.references", "Bibliography is available")
def check_quarto_config(ctx: RepositoryContext) -> CheckResult: return file_exists(ctx, "_quarto.yml", "files.quarto_config", "Quarto config is available")
def check_index(ctx: RepositoryContext) -> CheckResult: return file_exists(ctx, "index.qmd", "files.index", "Index page is available")
def check_syllabus(ctx: RepositoryContext) -> CheckResult: return file_exists(ctx, "syllabus.qmd", "files.syllabus", "Syllabus is available")
def check_teaching_notes(ctx: RepositoryContext) -> CheckResult: return file_exists(ctx, "teaching_notes.qmd", "files.teaching_notes", "Teaching notes are available")
def check_feedback(ctx: RepositoryContext) -> CheckResult: return file_exists(ctx, "feedback.qmd", "files.feedback", "Feedback page is available")


def check_quarto_project(ctx: RepositoryContext) -> CheckResult:
    if not ctx.path:
        return result("project.quarto", "Repository is a Quarto project", "not_checked", "Repository is not available")
    has_config = (ctx.path / "_quarto.yml").exists()
    has_qmd = any(ctx.path.glob("*.qmd"))
    status = "pass" if has_config and has_qmd else "fail"
    return result("project.quarto", "Repository is a Quarto project", status, "Found _quarto.yml and QMD files" if status == "pass" else "Missing _quarto.yml or QMD files")


def check_license(ctx: RepositoryContext) -> CheckResult:
    if not ctx.path:
        return result("license.file", "License file is available", "not_checked", "Repository is not available")
    matches = [p.name for p in ctx.path.iterdir() if p.is_file() and p.name.lower().startswith(("license", "licence"))]
    return result("license.file", "License file is available", "pass" if matches else "fail", "Found license file" if matches else "Missing license file", files=matches)


def check_cc_by_license(ctx: RepositoryContext) -> CheckResult:
    if not ctx.path:
        return result("license.cc_by", "Default teaching-content license is CC BY", "not_checked", "Repository is not available")
    files = [p for p in ctx.path.iterdir() if p.is_file() and p.name.lower().startswith(("license", "licence", "readme"))]
    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore")[:20000] for p in files)
    if re.search(r"CC[- ]?BY|Creative Commons Attribution", text, re.IGNORECASE):
        return result("license.cc_by", "Default teaching-content license is CC BY", "pass", "Detected CC BY license text")
    return result("license.cc_by", "Default teaching-content license is CC BY", "warning", "Could not detect CC BY license text")


def check_dir(ctx: RepositoryContext, dirname: str, check_id: str, label: str) -> CheckResult:
    if ctx.metadata.repository_type != "materials":
        return result(check_id, label, "not_applicable", "Only applicable to materials repositories")
    if not ctx.path:
        return result(check_id, label, "not_checked", "Repository is not available")
    exists = (ctx.path / dirname).is_dir()
    return result(check_id, label, "pass" if exists else "fail", f"{'Found' if exists else 'Missing'} {dirname}/", path=dirname)


def check_slides_directory(ctx: RepositoryContext) -> CheckResult: return check_dir(ctx, "slides", "dirs.slides", "Slides directory is available")
def check_notes_directory(ctx: RepositoryContext) -> CheckResult: return check_dir(ctx, "notes", "dirs.notes", "Notes directory is available")
def check_exercises_directory(ctx: RepositoryContext) -> CheckResult: return check_dir(ctx, "exercises", "dirs.exercises", "Exercises directory is available")


def check_make_pdfs_target(ctx: RepositoryContext) -> CheckResult:
    if ctx.metadata.repository_type != "materials":
        return result("make.pdfs", "Makefile has a pdfs target", "not_applicable", "Only applicable to materials repositories")
    if not ctx.path or not (ctx.path / "Makefile").exists():
        return result("make.pdfs", "Makefile has a pdfs target", "not_checked", "Makefile is not available")
    text = (ctx.path / "Makefile").read_text(encoding="utf-8", errors="ignore")
    found = re.search(r"^pdfs\s*:", text, re.MULTILINE) is not None
    return result("make.pdfs", "Makefile has a pdfs target", "pass" if found else "fail", "Found pdfs target" if found else "Missing pdfs target")


def check_session_materials(ctx: RepositoryContext) -> CheckResult:
    if ctx.metadata.repository_type != "materials":
        return result("materials.session_files", "Session materials use separate files", "not_applicable", "Only applicable to materials repositories")
    if not ctx.path or not (ctx.path / "slides").is_dir():
        return result("materials.session_files", "Session materials use separate files", "not_checked", "slides/ is not available")
    qmds = list((ctx.path / "slides").glob("*.qmd"))
    if len(qmds) >= 3:
        return result("materials.session_files", "Session materials use separate files", "pass", f"Found {len(qmds)} slide source files", count=len(qmds))
    if len(qmds) == 1:
        return result("materials.session_files", "Session materials use separate files", "warning", "Only one slide source file found", count=1)
    return result("materials.session_files", "Session materials use separate files", "not_checked", "No slide source files found", count=len(qmds))


def github_request(path: str, token: str | None) -> tuple[int, Any]:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"https://api.github.com{path}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {}
    except OSError:
        return 0, {}


def load_github_metadata(repo: Repository, token: str | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    status, metadata = github_request(f"/repos/{repo.repository}", token)
    if status != 200:
        return None, None
    protection_status, protection = github_request(f"/repos/{repo.repository}/branches/{metadata.get('default_branch', 'main')}/protection", token)
    return metadata, protection if protection_status == 200 else None


def github_not_checked(check_id: str, label: str) -> CheckResult:
    return result(check_id, label, "not_checked", "GitHub API metadata is not available or permission is missing")


def check_github_public(ctx: RepositoryContext) -> CheckResult:
    if ctx.github_metadata is None: return github_not_checked("github.public", "Repository is public")
    private = bool(ctx.github_metadata.get("private"))
    return result("github.public", "Repository is public", "pass" if not private else "fail", "Repository is public" if not private else "Repository is private")


def check_github_topic_teaching(ctx: RepositoryContext) -> CheckResult:
    if ctx.github_metadata is None: return github_not_checked("github.topic_teaching", "Repository has teaching topic")
    topics = ctx.github_metadata.get("topics") or []
    return result("github.topic_teaching", "Repository has teaching topic", "pass" if "teaching" in topics else "fail", "Found teaching topic" if "teaching" in topics else "Missing teaching topic", topics=topics)


def check_github_topic_materials(ctx: RepositoryContext) -> CheckResult:
    if ctx.metadata.repository_type != "materials": return result("github.topic_teaching_materials", "Repository has teaching-materials topic", "not_applicable", "Only applicable to materials repositories")
    if ctx.github_metadata is None: return github_not_checked("github.topic_teaching_materials", "Repository has teaching-materials topic")
    topics = ctx.github_metadata.get("topics") or []
    return result("github.topic_teaching_materials", "Repository has teaching-materials topic", "pass" if "teaching-materials" in topics else "fail", "Found teaching-materials topic" if "teaching-materials" in topics else "Missing teaching-materials topic", topics=topics)


def check_github_homepage(ctx: RepositoryContext) -> CheckResult:
    if ctx.github_metadata is None: return github_not_checked("github.homepage", "Homepage points to GitHub Pages")
    homepage = str(ctx.github_metadata.get("homepage") or "")
    ok = "github.io" in homepage
    return result("github.homepage", "Homepage points to GitHub Pages", "pass" if ok else "warning", "Homepage points to GitHub Pages" if ok else "Homepage is missing or does not point to GitHub Pages", homepage=homepage)


def check_default_branch(ctx: RepositoryContext) -> CheckResult:
    if ctx.github_metadata is None: return github_not_checked("github.default_branch", "Default branch is main")
    branch = ctx.github_metadata.get("default_branch")
    return result("github.default_branch", "Default branch is main", "pass" if branch == "main" else "fail", f"Default branch is {branch!r}", default_branch=branch)


def check_branch_protection(ctx: RepositoryContext) -> CheckResult:
    if ctx.branch_protection is None:
        return github_not_checked("github.branch_protection", "Main branch blocks force pushes and deletion")
    force = (ctx.branch_protection.get("allow_force_pushes") or {}).get("enabled")
    deletion = (ctx.branch_protection.get("allow_deletions") or {}).get("enabled")
    ok = force is False and deletion is False
    return result("github.branch_protection", "Main branch blocks force pushes and deletion", "pass" if ok else "fail", "Branch protection blocks force pushes and deletion" if ok else "Branch protection does not block force pushes and deletion", allow_force_pushes=force, allow_deletions=deletion)


COMMON_CHECKS: list[Callable[[RepositoryContext], CheckResult]] = [check_accessible, check_quarto_project, check_readme, check_license, check_cc_by_license, check_makefile, check_references, check_quarto_config, check_index, check_github_public, check_github_topic_teaching, check_github_homepage, check_default_branch, check_branch_protection]
MATERIALS_CHECKS: list[Callable[[RepositoryContext], CheckResult]] = [check_syllabus, check_teaching_notes, check_feedback, check_slides_directory, check_notes_directory, check_exercises_directory, check_make_pdfs_target, check_session_materials, check_github_topic_materials]
EXAM_CHECKS: list[Callable[[RepositoryContext], CheckResult]] = []


def overall_status(checks: list[CheckResult], errors: list[str]) -> str:
    meaningful = [c for c in checks if c.status not in {"not_applicable", "not_checked"}]
    if errors or any(c.status == "error" for c in checks): return "error"
    if any(c.status == "fail" for c in checks): return "fail"
    if any(c.status == "warning" for c in checks): return "warning"
    if meaningful and all(c.status == "pass" for c in meaningful): return "pass"
    return "not_checked"


def run_checks(repo: Repository, args: argparse.Namespace) -> dict[str, Any]:
    path, commit, errors = resolve_repository(repo, args.workspace, args.cache_dir, args.offline)
    token = os.getenv("GITHUB_TOKEN")
    github_metadata, branch_protection = (None, None) if args.offline else load_github_metadata(repo, token)
    ctx = RepositoryContext(repo, path, commit, github_metadata, branch_protection)
    checks: list[CheckResult] = []
    for check in [*COMMON_CHECKS, *(MATERIALS_CHECKS if repo.repository_type == "materials" else EXAM_CHECKS)]:
        try:
            checks.append(check(ctx))
        except Exception as exc:  # isolate check-level failures
            checks.append(result(f"error.{check.__name__}", check.__name__, "error", str(exc)))
    counts = dict(Counter(c.status for c in checks))
    for status in STATUSES:
        counts.setdefault(status, 0)
    return {**asdict(repo), "commit": commit, "overall_status": overall_status(checks, errors), "counts": counts, "checks": [asdict(c) for c in checks], "errors": errors}


def build_report(repositories: list[Repository], args: argparse.Namespace) -> dict[str, Any]:
    return {"generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"), "checker_version": script_commit(), "course_pages_dir": str(args.course_pages_dir), "repositories": [run_checks(r, args) for r in repositories]}


def script_commit() -> str | None:
    proc = run_git(["rev-parse", "HEAD"], cwd=handbook_root(), check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


def write_json(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def qmd_escape(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_qmd(report: dict[str, Any], path: Path) -> None:
    lines = ["<!-- Generated by src/repository_conformance.py; do not edit manually. -->", "", f"Generated at: `{report['generated_at']}`.", "", "Statuses: ✅ pass, ⚠️ warning, ❌ fail, ➖ not applicable, ❔ not checked, 🛑 error.", "", "| Repository | Type | Overall | Pass | Warning | Fail | Not checked | Error |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for repo in report["repositories"]:
        counts = repo["counts"]
        link = f"[{repo['repository']}]({repo['repository_url']})"
        lines.append(f"| {link} | {repo['repository_type']} | {STATUS_LABELS[repo['overall_status']]} | {counts['pass']} | {counts['warning']} | {counts['fail']} | {counts['not_checked']} | {counts['error']} |")
    lines.append("")
    for repo in report["repositories"]:
        lines.extend(["::: {.callout-note collapse=true}", f"## {repo['repository']} ({repo['repository_type']})", "", f"Course: {repo['course_id']} — {repo['course']}", "", f"Source page: `{repo['source_path']}`", "", f"Checked commit: `{repo.get('commit') or 'not available'}`", ""])
        if repo.get("errors"):
            lines.extend(["Repository-level errors:", *[f"- {qmd_escape(e)}" for e in repo["errors"]], ""])
        lines.extend(["| Check | Status | Message |", "|---|---:|---|"])
        for check in repo["checks"]:
            lines.append(f"| {qmd_escape(check['label'])} | {STATUS_LABELS[check['status']]} | {qmd_escape(check['message'])} |")
        lines.extend([":::", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    root = handbook_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=None, help="Directory containing existing local clones")
    parser.add_argument("--cache-dir", type=Path, default=root / ".cache" / "repository-conformance")
    parser.add_argument("--course-pages-dir", type=Path, default=root / "teaching" / "courses")
    parser.add_argument("--output-json", type=Path, default=root / "assets" / "reports" / "repository-conformance.json")
    parser.add_argument("--output-qmd", type=Path, default=root / "teaching" / "_generated" / "repository-conformance.qmd")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--repository", help="Only check one discovered repository, as owner/name")
    parser.add_argument("--fail-on-nonconformance", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repositories = discover_repositories(args.course_pages_dir)
    if args.repository:
        repositories = [r for r in repositories if r.repository.lower() == args.repository.lower()]
        if not repositories:
            print(f"Repository {args.repository!r} was not discovered from course metadata.", file=sys.stderr)
            return 2
    report = build_report(repositories, args)
    write_json(report, args.output_json)
    render_qmd(report, args.output_qmd)
    if args.fail_on_nonconformance and any(r["overall_status"] in {"fail", "error"} for r in report["repositories"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
