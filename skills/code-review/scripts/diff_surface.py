#!/usr/bin/env python3
"""
diff-surface.py — characterize the review surface of a diff.

USAGE
    diff-surface.py <repo-dir> [--base SHA] [--head SHA]

ARGUMENTS
    repo-dir   Absolute or relative path to the git repo.
    --base     Base commit SHA or ref. Default: HEAD~1.
    --head     Head commit SHA or ref. Default: HEAD.

OUTPUT (stdout)
    JSON with:
      base                    resolved short SHA
      head                    resolved short SHA
      files_changed           total count
      loc_added               total lines added
      loc_removed             total lines removed
      test_files_changed      count
      source_files_changed    count
      config_files_changed    count
      new_files               count of added files
      deleted_files           count of deleted files
      test_source_ratio       test_loc_added / source_loc_added, or 0.0 if no source
      complexity_delta        sum of complexity changes across source files
      files                   list of {path, category, loc_added, loc_removed,
                                        is_new, is_deleted}

EXIT CODES
    0  success
    1  not a git repo, git not found, or invalid ref
    2  bad arguments
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from hotspot import compute_complexity_from_text, _CF_KEYWORDS, _is_comment_line  # noqa: F401


def _git(args: list[str], cwd: str) -> str:
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout
    except subprocess.CalledProcessError:
        sys.exit(1)
    except FileNotFoundError:
        sys.exit(1)


def _git_safe(args: list[str], cwd: str) -> str | None:
    """Like _git but returns None on failure instead of exiting."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        return result.stdout
    except (FileNotFoundError, OSError):
        return None


def _validate_git_repo(repo_dir: str) -> str:
    repo_dir = os.path.abspath(repo_dir)
    if not os.path.isdir(repo_dir):
        sys.exit(1)
    _git(["rev-parse", "--git-dir"], repo_dir)
    return repo_dir


_TEST_PATTERNS = [
    lambda p: Path(p).stem.startswith("test_"),
    lambda p: Path(p).stem.endswith("_test"),
    lambda p: "_test." in Path(p).name,
    lambda p: "spec." in Path(p).name.lower(),
    lambda p: Path(p).stem.lower().endswith("spec"),
    lambda p: ".test." in Path(p).name,
    lambda p: "Tests/" in p or "/tests/" in p.lower(),
    lambda p: "__tests__" in p,
    lambda p: Path(p).stem.startswith("Test") and Path(p).suffix in (".swift", ".kt", ".java"),
]

_CONFIG_EXTENSIONS = {
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env",
    ".xml", ".plist", ".proto", ".graphql", ".sql", ".lock", ".gradle",
    ".podspec", ".gemspec", ".properties",
}

_CONFIG_NAMES = {
    "Makefile", "Dockerfile", "Jenkinsfile", "Procfile", "Vagrantfile",
    ".gitignore", ".gitattributes", ".editorconfig", ".eslintrc", ".babelrc",
    ".prettierrc", "Gemfile", "Pipfile",
}


def classify_file(path: str) -> str:
    name = Path(path).name
    ext = Path(path).suffix.lower()
    if any(fn(path) for fn in _TEST_PATTERNS):
        return "test"
    if ext in _CONFIG_EXTENSIONS or name in _CONFIG_NAMES:
        return "config"
    return "source"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("repo_dir")
    parser.add_argument("--base", default=None)
    parser.add_argument("--head", default=None)
    args = parser.parse_args(argv)

    repo = _validate_git_repo(args.repo_dir)

    base_ref = args.base or "HEAD~1"
    head_ref = args.head or "HEAD"

    base_sha = _git(["rev-parse", "--short", base_ref], repo).strip()
    head_sha = _git(["rev-parse", "--short", head_ref], repo).strip()

    numstat_raw = _git(["diff", "--numstat", f"{base_sha}..{head_sha}"], repo)
    status_raw = _git(["diff", "--name-status", f"{base_sha}..{head_sha}"], repo)

    new_files: set[str] = set()
    deleted_files: set[str] = set()
    for line in status_raw.splitlines():
        parts = line.split("\t")
        if not parts:
            continue
        status = parts[0]
        fname = parts[-1]
        if status.startswith("A"):
            new_files.add(fname)
        elif status.startswith("D"):
            deleted_files.add(fname)

    files_out: list[dict] = []
    totals: dict[str, int] = {
        "loc_added": 0, "loc_removed": 0,
        "test_files": 0, "source_files": 0, "config_files": 0,
        "test_loc_added": 0, "source_loc_added": 0,
    }

    for line in numstat_raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added_str, removed_str = parts[0], parts[1]
        path = parts[2]

        # Handle renames: "old\tnew" or "{old => new}" — use new path
        if "\t" in path:
            path = path.split("\t")[1]

        added = 0 if added_str == "-" else int(added_str)
        removed = 0 if removed_str == "-" else int(removed_str)

        category = classify_file(path)
        is_new = path in new_files
        is_deleted = path in deleted_files

        files_out.append({
            "path": path,
            "category": category,
            "loc_added": added,
            "loc_removed": removed,
            "is_new": is_new,
            "is_deleted": is_deleted,
        })

        totals["loc_added"] += added
        totals["loc_removed"] += removed
        totals[f"{category}_files"] += 1
        if category == "test":
            totals["test_loc_added"] += added
        elif category == "source":
            totals["source_loc_added"] += added

    # Complexity delta for non-deleted source files
    complexity_delta = 0
    for f in files_out:
        if f["category"] != "source" or f["is_deleted"]:
            continue
        before_text = _git_safe(["show", f"{base_sha}:{f['path']}"], repo) or ""
        after_text = _git_safe(["show", f"{head_sha}:{f['path']}"], repo) or ""
        complexity_delta += (
            compute_complexity_from_text(after_text)
            - compute_complexity_from_text(before_text)
        )

    src_loc = totals["source_loc_added"]
    test_loc = totals["test_loc_added"]
    if src_loc > 0:
        ratio = round(test_loc / src_loc, 3)
    elif test_loc > 0:
        ratio = None  # test LOC but no source LOC → undefined
    else:
        ratio = 0.0

    output = {
        "base": base_sha,
        "head": head_sha,
        "files_changed": len(files_out),
        "loc_added": totals["loc_added"],
        "loc_removed": totals["loc_removed"],
        "test_files_changed": totals["test_files"],
        "source_files_changed": totals["source_files"],
        "config_files_changed": totals["config_files"],
        "new_files": len(new_files),
        "deleted_files": len(deleted_files),
        "test_source_ratio": ratio,
        "complexity_delta": complexity_delta,
        "files": files_out,
    }
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
