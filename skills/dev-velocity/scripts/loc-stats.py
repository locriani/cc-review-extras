#!/usr/bin/env python3
"""
loc-stats.py — compute code output rate metrics from a git repository.

USAGE
    loc-stats.py <repo-dir> [--since ANCHOR] [--hours N] [--exclude GLOB ...]

ARGUMENTS
    repo-dir     Absolute or relative path to the git repo
    --since      Anchor: ISO date (YYYY-MM-DD), commit SHA, branch name, or
                 relative ("2 weeks ago"). Defaults to first commit.
    --hours      Known hours of development (e.g. from time-estimation). When
                 provided, LOC/hr and hrs/LOC are computed from this value.
                 When omitted, the script reports LOC and commit stats only.
    --exclude    Glob pattern(s) to exclude (e.g. '*.generated.swift').
                 Can be repeated. Always excludes *.pb.swift by default.

OUTPUT (stdout)
    JSON with:
      anchor             resolved anchor (commit SHA + date), or null
      since_date         ISO date string used in git log, or null
      commits            total commit count in range
      insertions         total lines added (net)
      deletions          total lines removed
      net_loc            insertions (the primary LOC metric)
      hours              hours passed in (or null)
      loc_per_hour       net_loc / hours, or null
      seconds_per_loc    3600 / loc_per_hour, or null
      loc_per_commit     net_loc / commits, or null
      squash_detected    bool — true if 3+ commits within a 5-min window
      squash_bursts      list of {window_start, window_end, commit_count}
      excluded_patterns  patterns applied

EXIT CODES
    0  success
    1  git not found or not a git repo
    2  bad arguments
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_EXCLUDES = ["*.pb.swift", "*.generated.*", "*.xcassets"]
SQUASH_WINDOW_SECONDS = 300
SQUASH_MIN_COMMITS = 3


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("repo_dir", help="Path to the git repository")
    p.add_argument("--since", default=None, help="Anchor: ISO date, SHA, branch, or relative phrase")
    p.add_argument("--hours", type=float, default=None, help="Known active hours from time-estimation")
    p.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                   help="Glob to exclude from LOC count (repeatable)")
    return p.parse_args()


def git(cmd: list[str], cwd: str) -> str:
    try:
        r = subprocess.run(["git"] + cmd, cwd=cwd, capture_output=True, text=True, check=True)
        return r.stdout
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"git error: {e.stderr.strip()}\n")
        sys.exit(1)
    except FileNotFoundError:
        sys.stderr.write("FAIL: git not found in PATH\n")
        sys.exit(1)


def resolve_anchor(repo: str, since: str | None) -> tuple[str | None, str | None]:
    if since is None:
        return None, None
    if re.match(r"^\d{4}-\d{2}-\d{2}$", since):
        return None, since
    try:
        date_raw = subprocess.run(
            ["git", "log", "-1", "--format=%ai", since],
            cwd=repo, capture_output=True, text=True, check=True
        ).stdout.strip()
        since_date = date_raw[:10]
        sha = subprocess.run(
            ["git", "rev-parse", "--short", since],
            cwd=repo, capture_output=True, text=True, check=True
        ).stdout.strip()
        return sha, since_date
    except subprocess.CalledProcessError:
        return None, since


def get_commit_timestamps(repo: str, since: str | None) -> list[datetime]:
    cmd = ["log", "--format=%ai"]
    if since:
        cmd += [f"--since={since}"]
    raw = git(cmd, cwd=repo)
    results = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            dt = datetime.fromisoformat(line.replace(" ", "T", 1).rsplit(" ", 1)[0])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            results.append(dt)
        except ValueError:
            continue
    return sorted(results)


def detect_squash_bursts(timestamps: list[datetime]) -> tuple[bool, list[dict]]:
    if not timestamps:
        return False, []
    bursts = []
    i = 0
    while i < len(timestamps):
        j = i + 1
        while j < len(timestamps):
            if (timestamps[j] - timestamps[i]).total_seconds() <= SQUASH_WINDOW_SECONDS:
                j += 1
            else:
                break
        count = j - i
        if count >= SQUASH_MIN_COMMITS:
            bursts.append({
                "window_start": timestamps[i].isoformat(),
                "window_end": timestamps[j - 1].isoformat(),
                "commit_count": count,
            })
            i = j
        else:
            i += 1
    return len(bursts) > 0, bursts


def get_loc_stats(repo: str, since: str | None, excludes: list[str]) -> tuple[int, int]:
    cmd = ["log", "--stat", "--pretty=tformat:"]
    if since:
        cmd += [f"--since={since}"]
    raw = git(cmd, cwd=repo)

    all_excludes = DEFAULT_EXCLUDES + excludes
    insertions = 0
    deletions = 0
    for line in raw.splitlines():
        m = re.match(r"^\s+(.+?)\s+\|\s+\d+\s+([+\-]+)?", line)
        if not m:
            continue
        filepath = m.group(1).strip()
        filename = Path(filepath).name
        if any(fnmatch.fnmatch(filename, pat) for pat in all_excludes):
            continue
        changes = m.group(2) or ""
        insertions += changes.count("+")
        deletions += changes.count("-")
    return insertions, deletions


def main() -> int:
    args = parse_args()
    repo = str(Path(args.repo_dir).resolve())

    try:
        subprocess.run(["git", "rev-parse", "--git-dir"], cwd=repo,
                       capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        sys.stderr.write(f"FAIL: not a git repository: {repo}\n")
        return 1

    sha, since_date = resolve_anchor(repo, args.since)
    timestamps = get_commit_timestamps(repo, since_date)
    commit_count = len(timestamps)
    squash_detected, squash_bursts = detect_squash_bursts(timestamps)
    insertions, deletions = get_loc_stats(repo, since_date, args.exclude)

    hours = args.hours
    loc_per_hour = round(insertions / hours, 1) if hours and insertions else None
    seconds_per_loc = round(3600 / loc_per_hour, 1) if loc_per_hour else None
    loc_per_commit = round(insertions / commit_count, 1) if commit_count else None

    out = {
        "anchor": sha,
        "since_date": since_date,
        "commits": commit_count,
        "insertions": insertions,
        "deletions": deletions,
        "net_loc": insertions,
        "hours": hours,
        "loc_per_hour": loc_per_hour,
        "seconds_per_loc": seconds_per_loc,
        "loc_per_commit": loc_per_commit,
        "squash_detected": squash_detected,
        "squash_bursts": squash_bursts,
        "excluded_patterns": DEFAULT_EXCLUDES + args.exclude,
    }
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
