#!/usr/bin/env bash
# git-clusters.sh — list commits in a repo since an anchor, grouped into work
# sessions. Treats any commit-time gap > 2h as a session break (configurable).
#
# USAGE
#     git-clusters.sh <repo-dir> <anchor> [--gap-minutes N]
#
#     <anchor>  Anything `git log --since=` accepts. Examples:
#                 2025-01-01
#                 "2 weeks ago"
#                 <commit-sha>          (uses that commit's author date)
#                 <branch-name>         (uses that branch tip's author date)
#
# OUTPUT (stdout)
#     One header line per session:
#         === session N: YYYY-MM-DD HH:MM → YYYY-MM-DD HH:MM (Hh Mm, K commits) ===
#     Followed by indented lines, one per commit:
#         <iso-timestamp>  <subject>
#
# EXAMPLE
#     ./git-clusters.sh /path/to/your/project 2025-06-01
#     ./git-clusters.sh /path/to/your/project deadbeef --gap-minutes 90
#
# EXIT CODES
#     0  success (even if zero commits in range)
#     1  repo dir is not a git repo
#     2  bad arguments
set -uo pipefail

if [[ $# -lt 2 ]]; then
  sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
fi

REPO_DIR="$1"; shift
ANCHOR="$1"; shift
GAP_MIN=120  # default 2h

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gap-minutes)
      [[ $# -ge 2 ]] || { echo "ABORT: --gap-minutes needs a value" >&2; exit 2; }
      GAP_MIN="$2"; shift 2 ;;
    -h|--help) sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "ABORT: unknown arg '$1'" >&2; exit 2 ;;
  esac
done

[[ -d "$REPO_DIR/.git" ]] || { echo "FAIL: not a git repo: $REPO_DIR" >&2; exit 1; }

# Resolve <anchor>: if it's a valid git ref, use its committer date; otherwise
# pass it through as-is to --since (handles "2 weeks ago", ISO dates, etc.).
# Quirk: git's --since interprets bare 'YYYY-MM-DD' as end-of-day in local tz
# and silently drops same-day commits. Normalize bare dates to '00:00' so
# anchors like "2025-06-01" include commits made on June 1st.
if (cd "$REPO_DIR" && git rev-parse --verify --quiet "$ANCHOR" >/dev/null); then
  SINCE_ARG="$(cd "$REPO_DIR" && git log -1 --format=%aI "$ANCHOR")"
elif [[ "$ANCHOR" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  SINCE_ARG="$ANCHOR 00:00"
else
  SINCE_ARG="$ANCHOR"
fi

# Fetch commits oldest-first. Format: <ISO-ts>\t<subject>. Tab-delimited so
# subjects can contain any non-tab character.
GIT_OUT="$(cd "$REPO_DIR" && git log --reverse --since="$SINCE_ARG" --pretty=format:'%aI%x09%s')"

if [[ -z "$GIT_OUT" ]]; then
  echo "(no commits in range)"
  exit 0
fi

# Cluster via python3. The heredoc IS the script (python3 -), so we pass git
# output through an env var rather than stdin (stdin is already taken by the
# heredoc).
GIT_OUT="$GIT_OUT" GAP_MIN="$GAP_MIN" python3 - <<'PY'
import os, sys
from datetime import datetime

gap_sec = int(os.environ["GAP_MIN"]) * 60

parsed = []
for line in os.environ["GIT_OUT"].splitlines():
    line = line.rstrip("\n")
    if not line:
        continue
    ts_str, _, subject = line.partition("\t")
    try:
        ts = datetime.fromisoformat(ts_str)
    except ValueError:
        continue
    parsed.append((ts, subject))

if not parsed:
    print("(no parseable commits)")
    sys.exit(0)

sessions = [[parsed[0]]]
for prev, curr in zip(parsed, parsed[1:]):
    if (curr[0] - prev[0]).total_seconds() > gap_sec:
        sessions.append([curr])
    else:
        sessions[-1].append(curr)

for i, sess in enumerate(sessions, 1):
    start, end = sess[0][0], sess[-1][0]
    h, rem = divmod(int((end - start).total_seconds()), 3600)
    m = rem // 60
    n = len(sess)
    plural = "s" if n != 1 else ""
    print(f"=== session {i}: {start:%Y-%m-%d %H:%M} → {end:%Y-%m-%d %H:%M} ({h}h {m}m, {n} commit{plural}) ===")
    for ts, subj in sess:
        print(f"  {ts.isoformat()}  {subj}")
    print()
PY
