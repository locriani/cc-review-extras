#!/usr/bin/env python3
"""
coupling.py — find files that frequently change together (temporal coupling).

USAGE
    coupling.py <repo-dir> [--since ANCHOR] [--min-support N] [--top N]
                           [--exclude GLOB ...] [--max-files-per-commit N]

ARGUMENTS
    repo-dir               Absolute or relative path to the git repo.
    --since                Anchor: ISO date, commit SHA, branch, or relative phrase.
                           Defaults to all history.
    --min-support          Minimum co-change count to include a pair. Default: 3.
    --top                  Return only the top N pairs. Default: 30.
    --exclude              Glob pattern to exclude (repeatable).
    --max-files-per-commit Cap per-commit file set to avoid monorepo noise. Default: 50.

OUTPUT (stdout)
    JSON with:
      generated_at    ISO 8601 UTC
      repo            resolved absolute path
      since           anchor as passed (or null)
      min_support     effective min_support used
      pairs           list of {file_a, file_b, co_changes, coupling_strength, implied_risk}
                      sorted descending by coupling_strength, then co_changes

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
from collections import Counter
from datetime import datetime, timezone
from itertools import combinations


def _matches_any(path: str, globs: list[str]) -> bool:
    name = os.path.basename(path)
    return any(fnmatch.fnmatch(name, g) or fnmatch.fnmatch(path, g) for g in globs)


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


def _git_allow_empty(args: list[str], cwd: str) -> str:
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


def _validate_git_repo(repo_dir: str) -> str:
    repo_dir = os.path.abspath(repo_dir)
    if not os.path.isdir(repo_dir):
        sys.exit(1)
    _git(["rev-parse", "--git-dir"], repo_dir)
    return repo_dir


_SHA_RE = re.compile(r'^[0-9a-f]{40}$')


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("repo_dir")
    parser.add_argument("--since", default=None)
    parser.add_argument("--min-support", type=int, default=3)
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--max-files-per-commit", type=int, default=50)
    args = parser.parse_args(argv)

    if args.min_support <= 0:
        parser.error("--min-support must be a positive integer")
        sys.exit(2)
    if args.top <= 0:
        parser.error("--top must be a positive integer")
        sys.exit(2)

    repo = _validate_git_repo(args.repo_dir)

    since_args: list[str] = []
    if args.since:
        since_val = args.since
        if re.match(r'^[0-9a-f]{4,40}$', since_val, re.IGNORECASE):
            since_args = [f"{since_val}..HEAD"]
        else:
            since_args = [f"--since={since_val}"]

    git_log_args = [
        "log", "--name-only", "--pretty=format:%H", "--diff-filter=ACDMRT",
    ] + since_args

    raw = _git_allow_empty(git_log_args, repo)

    commit_file_sets: list[set[str]] = []
    current_set: set[str] = set()

    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _SHA_RE.match(stripped):
            # New commit boundary
            if current_set:
                commit_file_sets.append(current_set)
            current_set = set()
        else:
            if not _matches_any(stripped, args.exclude):
                if len(current_set) < args.max_files_per_commit:
                    current_set.add(stripped)
    if current_set:
        commit_file_sets.append(current_set)

    file_change_count: Counter[str] = Counter()
    pair_count: Counter[tuple[str, str]] = Counter()

    for file_set in commit_file_sets:
        for f in file_set:
            file_change_count[f] += 1
        if len(file_set) < 2:
            continue
        for a, b in combinations(sorted(file_set), 2):
            pair_count[(a, b)] += 1

    pairs_out: list[dict] = []
    for (a, b), co in pair_count.items():
        if co < args.min_support:
            continue
        max_changes = max(file_change_count[a], file_change_count[b])
        strength = round(co / max_changes, 3) if max_changes > 0 else 0.0
        if strength >= 0.7:
            risk = "high"
        elif strength >= 0.4:
            risk = "medium"
        else:
            risk = "low"
        pairs_out.append({
            "file_a": a,
            "file_b": b,
            "co_changes": co,
            "coupling_strength": strength,
            "implied_risk": risk,
        })

    pairs_out.sort(key=lambda x: (-x["coupling_strength"], -x["co_changes"]))
    pairs_out = pairs_out[:args.top]

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo": repo,
        "since": args.since,
        "min_support": args.min_support,
        "pairs": pairs_out,
    }
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
