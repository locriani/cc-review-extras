#!/usr/bin/env python3
"""
hotspot.py — find files that are both high-churn and high-complexity (hotspot pattern).

USAGE
    hotspot.py <repo-dir> [--since ANCHOR] [--top N] [--exclude GLOB ...]

ARGUMENTS
    repo-dir      Absolute or relative path to the git repo.
    --since       Anchor: ISO date, commit SHA, branch, or relative phrase ("2 weeks ago").
                  Defaults to all history.
    --top         Return only the top N files by hotspot_score. Default: 20.
    --exclude     Glob pattern to exclude (repeatable). E.g. '*.generated.swift'.

OUTPUT (stdout)
    JSON with:
      generated_at        ISO 8601 UTC timestamp
      repo                resolved absolute path
      since               anchor as passed (or null)
      files               list of {path, churn, complexity, hotspot_score, last_changed_iso}
                          sorted descending by hotspot_score

EXIT CODES
    0  success
    1  not a git repo or git not found
    2  bad arguments
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone


_CF_KEYWORDS = re.compile(
    r'\b(if|else|elif|for|while|case|switch|catch|try|except|finally)\b'
)
_COMMENT_PREFIXES = ("//", "#", "--", "*", "/*", "*/", "<!--")


def _is_comment_line(line: str) -> bool:
    return any(line.startswith(p) for p in _COMMENT_PREFIXES)


def compute_complexity(filepath: str) -> int:
    """Heuristic complexity: lines + 5× for each control-flow keyword line."""
    total = 0
    try:
        with open(filepath, encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                stripped = raw.strip()
                if not stripped or _is_comment_line(stripped):
                    continue
                total += 1
                if _CF_KEYWORDS.search(stripped):
                    total += 5
    except OSError:
        pass
    return total


def compute_complexity_from_text(text: str) -> int:
    """Same heuristic applied to an in-memory string."""
    total = 0
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or _is_comment_line(stripped):
            continue
        total += 1
        if _CF_KEYWORDS.search(stripped):
            total += 5
    return total


def _matches_any(path: str, globs: list[str]) -> bool:
    name = os.path.basename(path)
    return any(fnmatch.fnmatch(name, g) or fnmatch.fnmatch(path, g) for g in globs)


def _git_allow_empty(args: list[str], cwd: str) -> str:
    """Like _git but returns empty string instead of exiting on non-zero (e.g. no commits yet)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        return result.stdout
    except FileNotFoundError:
        sys.exit(1)


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


def _validate_git_repo(repo_dir: str) -> str:
    repo_dir = os.path.abspath(repo_dir)
    if not os.path.isdir(repo_dir):
        sys.exit(1)
    _git(["rev-parse", "--git-dir"], repo_dir)
    return repo_dir


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("repo_dir")
    parser.add_argument("--since", default=None)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--exclude", action="append", default=[])
    args = parser.parse_args(argv)

    if args.top <= 0:
        parser.error("--top must be a positive integer")
        sys.exit(2)

    repo = _validate_git_repo(args.repo_dir)

    since_args: list[str] = []
    if args.since:
        # Accept SHA/branch (--since-commit style via git log range) or date/relative
        # Try it as a ref first; if it looks like a date or relative phrase, use --since=
        since_val = args.since
        # If it's 40 hex chars or short SHA-ish, use it as a commit range anchor
        if re.match(r'^[0-9a-f]{4,40}$', since_val, re.IGNORECASE):
            since_args = [f"{since_val}..HEAD", "--"]
        else:
            since_args = [f"--since={since_val}"]

    git_log_args = ["log", "--name-only", "--format=%ai", "--diff-filter=ACDMRT"]
    if since_args and since_args[0].endswith("..HEAD"):
        # range mode: insert the range before --
        git_log_args = ["log", "--name-only", "--format=%ai", "--diff-filter=ACDMRT",
                        since_args[0]]
    elif since_args:
        git_log_args += since_args

    raw = _git_allow_empty(git_log_args, repo)

    churn_map: dict[str, int] = {}
    last_changed: dict[str, str] = {}

    current_date = ""
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Lines that look like ISO dates (start with digit + year-ish pattern)
        if re.match(r'^\d{4}-\d{2}-\d{2}', stripped):
            current_date = stripped
        elif current_date:
            # It's a filename line
            if not _matches_any(stripped, args.exclude):
                churn_map[stripped] = churn_map.get(stripped, 0) + 1
                prev = last_changed.get(stripped, "")
                if stripped not in last_changed or current_date > prev:
                    last_changed[stripped] = current_date

    complexity_map: dict[str, int] = {}
    for path in churn_map:
        abs_path = os.path.join(repo, path)
        if os.path.isfile(abs_path):
            complexity_map[path] = compute_complexity(abs_path)
        else:
            complexity_map[path] = 0

    max_c = max(complexity_map.values()) if complexity_map else 1
    if max_c == 0:
        max_c = 1

    results = []
    for path in churn_map:
        norm = complexity_map[path] / max_c
        score = round(churn_map[path] * norm, 3)
        results.append({
            "path": path,
            "churn": churn_map[path],
            "complexity": complexity_map[path],
            "hotspot_score": score,
            "last_changed_iso": last_changed.get(path, ""),
        })

    results.sort(key=lambda x: (-x["hotspot_score"], -x["churn"]))
    results = results[:args.top]

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo": repo,
        "since": args.since,
        "files": results,
    }
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
