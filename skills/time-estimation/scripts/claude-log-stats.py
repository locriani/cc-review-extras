#!/usr/bin/env python3
"""
claude-log-stats.py — extract active-time stats from a project's Claude Code
session logs.

USAGE
    claude-log-stats.py <project-dir> [--since YYYY-MM-DD[THH:MM]]
    claude-log-stats.py /path/to/your/project --since 2025-01-01

OUTPUT (stdout)
    JSON object with:
      log_dir            absolute path to the matched ~/.claude/projects/<slug>
      file_count         number of *.jsonl session files in scope
      event_count        total events with valid timestamps
      first_event        ISO 8601 (UTC) of earliest event
      last_event         ISO 8601 (UTC) of latest event
      wall_clock_hours   (last - first) / 3600
      active_hours_15m   sum of consecutive-event gaps ≤ 15 min, in hours
      active_hours_30m   sum of consecutive-event gaps ≤ 30 min, in hours
      chapter_breaks     list of {start, end, gap_minutes} for every gap > 15m
                         (strict > avoids double-counting the boundary against
                         active_hours_15m, which uses ≤ 15)

EXIT CODES
    0  success (even if zero events found — check event_count)
    1  log dir does not exist
    2  bad arguments

NOTES
- Claude Code names log dirs by replacing every non-alphanumeric character in
  the absolute project path with '-'. This script handles that translation.
- Timestamps in jsonl are ISO 8601 with a 'Z' suffix; we normalise to UTC.
- Lines without a parseable .timestamp are silently skipped.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from glob import glob
from pathlib import Path


def project_dir_to_log_slug(project_dir: str) -> str:
    """Translate a project's absolute path into Claude Code's log-dir name.
    Replaces every char that isn't [A-Za-z0-9.] with '-'."""
    abs_path = os.path.abspath(project_dir)
    return re.sub(r"[^A-Za-z0-9.]", "-", abs_path)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("project_dir", help="Absolute or relative path to the project repo")
    p.add_argument("--since", default=None, help="Drop events before this ISO timestamp (YYYY-MM-DD or full ISO)")
    return p.parse_args()


def parse_since(s: str | None) -> datetime | None:
    if s is None:
        return None
    # Validate the user's input shape BEFORE we tack on time/tz. Otherwise the
    # error message leaks our internal padding (e.g. 'notadateT00:00:00+00:00')
    # which is confusing when the user typed 'notadate'.
    has_time = "T" in s or " " in s
    candidate = s.replace("Z", "+00:00") if has_time else s + "T00:00:00+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        sys.exit(f"ABORT: bad --since value '{s}' — expected YYYY-MM-DD or full ISO 8601 (e.g. 2025-06-01T14:30:00)")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def collect_timestamps(log_dir: Path, since: datetime | None) -> tuple[list[datetime], int]:
    """Return (sorted_timestamps, file_count)."""
    files = sorted(glob(str(log_dir / "*.jsonl")))
    timestamps: list[datetime] = []
    for f in files:
        try:
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    t = obj.get("timestamp")
                    if not t:
                        continue
                    try:
                        dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    if since is not None and dt < since:
                        continue
                    timestamps.append(dt)
        except OSError:
            continue
    timestamps.sort()
    return timestamps, len(files)


def compute_active_hours(timestamps: list[datetime], threshold_minutes: float) -> float:
    """Sum gaps between consecutive events that are ≤ threshold."""
    cap = threshold_minutes * 60.0
    total_seconds = 0.0
    for a, b in zip(timestamps, timestamps[1:]):
        gap = (b - a).total_seconds()
        if 0 < gap <= cap:
            total_seconds += gap
    return total_seconds / 3600.0


def find_chapter_breaks(timestamps: list[datetime], min_minutes: float = 15.0) -> list[dict]:
    """Gaps strictly greater than min_minutes. Boundary is exclusive so a gap of
    exactly 15.0 min counts as still-active (per compute_active_hours), not a
    chapter break — avoids double-counting on the boundary."""
    breaks = []
    for a, b in zip(timestamps, timestamps[1:]):
        gap_min = (b - a).total_seconds() / 60.0
        if gap_min > min_minutes:
            breaks.append({
                "start": a.isoformat(),
                "end": b.isoformat(),
                "gap_minutes": round(gap_min, 1),
            })
    return breaks


def main() -> int:
    args = parse_args()
    home = Path.home()
    slug = project_dir_to_log_slug(args.project_dir)
    log_dir = home / ".claude" / "projects" / slug

    if not log_dir.is_dir():
        sys.stderr.write(f"FAIL: log dir does not exist: {log_dir}\n")
        sys.stderr.write("HINT: project may have no Claude Code history, or the slug translation differs.\n")
        sys.stderr.write(f"      tried slug = '{slug}' (from project path '{os.path.abspath(args.project_dir)}')\n")
        return 1

    since = parse_since(args.since)
    timestamps, file_count = collect_timestamps(log_dir, since)

    if not timestamps:
        json.dump({
            "log_dir": str(log_dir),
            "file_count": file_count,
            "event_count": 0,
            "first_event": None,
            "last_event": None,
            "wall_clock_hours": 0.0,
            "active_hours_15m": 0.0,
            "active_hours_30m": 0.0,
            "chapter_breaks": [],
        }, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    wall_hours = (timestamps[-1] - timestamps[0]).total_seconds() / 3600.0
    out = {
        "log_dir": str(log_dir),
        "file_count": file_count,
        "event_count": len(timestamps),
        "first_event": timestamps[0].isoformat(),
        "last_event": timestamps[-1].isoformat(),
        "wall_clock_hours": round(wall_hours, 2),
        "active_hours_15m": round(compute_active_hours(timestamps, 15.0), 2),
        "active_hours_30m": round(compute_active_hours(timestamps, 30.0), 2),
        "chapter_breaks": find_chapter_breaks(timestamps, 15.0),
    }
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
