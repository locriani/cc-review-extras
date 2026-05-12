#!/usr/bin/env python3
"""
bug-tally.py — count bugs introduced and classify where they were caught.

USAGE
    bug-tally.py <repo-dir> [--since ANCHOR] [--log-dir PATH]

ARGUMENTS
    repo-dir      Absolute or relative path to the git repo.
    --since       Anchor: ISO date (YYYY-MM-DD), commit SHA, branch name, or
                  relative phrase ("2 weeks ago"). Defaults to beginning of repo.
    --log-dir     Path to Claude Code log dir for this project. Defaults to
                  ~/.claude/projects/<auto-derived-slug>. Used to scan review
                  session transcripts for review-finding bugs.

OUTPUT (stdout)
    JSON with:
      since_date             ISO date anchor (or null)
      commits_scanned        total commits examined
      bugs_total             total bugs identified
      by_source              {
        fix_commit,          conventional fix: prefix
        subject_keyword,     subject-line bug keyword
        issue_close,         GitHub closes/fixes/resolves in body
        bundled_fix,         items inside bundled-fix commits
        review_finding,      bugs from Claude code review sessions
        test_failure,        test-driven fixes
        revert,              revert commits
      }
      by_stage               {
        in_dev,              fixed immediately in same session
        code_review,         caught via review (any mode)
        code_review_detail,  {single, multi_persona, brutal}
        test_suite,          CI/test failures
        manual_qa,           TestFlight / manual testing
        production,          customer or prod reports
        escaped,             estimated escaped (no fix found)
      }
      escaped_count          same as by_stage.escaped
      review_sessions_found  number of Claude review sessions detected
      log_dir                resolved log dir path (or null if not found)

EXIT CODES
    0  success
    1  git not found or not a git repo
    2  bad arguments
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from glob import glob
from pathlib import Path

# Subject-line keywords that strongly suggest a bug fix (case-insensitive)
BUG_SUBJECT_PATTERNS = re.compile(
    r"\b(bugfix|hotfix|revert|regression|off.by.one|nil.crash|crash(?:es|ing)?|"
    r"race.condition|deadlock|memory.leak|overflow|oops|accidentally|unintentional)\b"
    r"|(?<!\w)(bug|broken|wrong|incorrect|typo|invalid|repair)(?!\w)",
    re.IGNORECASE,
)

# GitHub-style issue-closing keywords in commit body
ISSUE_CLOSE_RE = re.compile(r"\b(close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", re.IGNORECASE)

# Bundled-fix patterns (commit body)
BUNDLED_RE = re.compile(
    r"land\s+actions?\s+\d+[–\-]\d+|address\s+\d+.{0,20}(agent|reviewer|review)\s+(finding|comment|action)|"
    r"fix\s+the\s+following|address\s+review\s+(comment|finding|action)",
    re.IGNORECASE,
)
NUMBERED_ITEM_RE = re.compile(r"^\s*\d+[\.\)]\s+.{5,}", re.MULTILINE)

# Claude review session indicators in .jsonl content
REVIEW_INDICATOR_RE = re.compile(
    r"(critical|high|medium)\s+(finding|severity|issue|bug|defect|problem)|"
    r"\*\*(Critical|High|Medium)\*\*.*?(finding|issue|bug)|"
    r"review\s+finding|review\s+result|land\s+action",
    re.IGNORECASE,
)
BRUTAL_INDICATOR_RE = re.compile(r"brutal|all.{0,10}persona|16.{0,10}persona", re.IGNORECASE)
MULTI_INDICATOR_RE = re.compile(r"\d.{0,5}(persona|agent|reviewer)", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("repo_dir", help="Path to the git repository")
    p.add_argument("--since", default=None)
    p.add_argument("--log-dir", default=None, dest="log_dir",
                   help="Path to Claude Code log dir (auto-derived if omitted)")
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


def resolve_since_date(repo: str, since: str | None) -> str | None:
    if since is None:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}$", since):
        return since
    # Try resolving as ref or relative phrase
    try:
        raw = subprocess.run(
            ["git", "log", "-1", "--format=%ai", since],
            cwd=repo, capture_output=True, text=True, check=True
        ).stdout.strip()
        return raw[:10]
    except subprocess.CalledProcessError:
        return since


def derive_log_dir(repo: str) -> Path | None:
    abs_path = os.path.abspath(repo)
    slug = re.sub(r"[^A-Za-z0-9.]", "-", abs_path)
    candidate = Path.home() / ".claude" / "projects" / slug
    return candidate if candidate.is_dir() else None


def get_commits(repo: str, since: str | None) -> list[dict]:
    """Return list of {sha, subject, body} dicts."""
    sep = "\x00COMMIT\x00"
    cmd = ["log", f"--pretty=format:%H{sep}%s{sep}%b{sep}END_BODY"]
    if since:
        cmd += [f"--since={since}"]
    raw = git(cmd, cwd=repo)

    commits = []
    for block in raw.split("END_BODY"):
        block = block.strip()
        if not block:
            continue
        parts = block.split(sep)
        if len(parts) < 3:
            continue
        commits.append({"sha": parts[0].strip(), "subject": parts[1].strip(), "body": parts[2].strip()})
    return commits


def classify_commits(commits: list[dict]) -> dict:
    """Classify each commit into bug sources. Returns counts by source."""
    by_source: dict[str, int] = defaultdict(int)
    closed_issues: set[str] = set()

    for c in commits:
        subject = c["subject"]
        body = c["body"]

        # 1. Conventional fix: prefix
        if re.match(r"^fix(\(.*?\))?:", subject, re.IGNORECASE):
            # Check if it's a bundled commit
            if BUNDLED_RE.search(subject) or BUNDLED_RE.search(body):
                items = NUMBERED_ITEM_RE.findall(body)
                count = max(len(items), 2)  # at least 2 if bundled pattern matched
                by_source["bundled_fix"] += count
            else:
                by_source["fix_commit"] += 1
            continue

        # 2. Revert commits
        if re.match(r"^revert\b", subject, re.IGNORECASE):
            by_source["revert"] += 1
            continue

        # 3. Subject-line bug keywords
        if BUG_SUBJECT_PATTERNS.search(subject):
            by_source["subject_keyword"] += 1
            continue

        # 4. Issue-closing keywords in body
        issue_matches = ISSUE_CLOSE_RE.findall(body)
        for _, issue_num in issue_matches:
            if issue_num not in closed_issues:
                closed_issues.add(issue_num)
                by_source["issue_close"] += 1

    return dict(by_source)


def scan_review_sessions(log_dir: Path | None) -> dict:
    if log_dir is None:
        return {"count": 0, "findings": 0, "modes": {"single": 0, "multi_persona": 0, "brutal": 0}}

    files = glob(str(log_dir / "*.jsonl"))
    review_sessions = 0
    total_findings = 0
    modes: dict[str, int] = {"single": 0, "multi_persona": 0, "brutal": 0}

    for fpath in files:
        session_text = ""
        try:
            with open(fpath, encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                        msg = obj.get("message", {})
                        content = msg.get("content", "")
                        if isinstance(content, list):
                            for c in content:
                                if isinstance(c, dict) and c.get("type") == "text":
                                    session_text += c["text"] + "\n"
                        elif isinstance(content, str):
                            session_text += content + "\n"
                    except (json.JSONDecodeError, AttributeError):
                        continue
        except OSError:
            continue

        if not REVIEW_INDICATOR_RE.search(session_text):
            continue

        review_sessions += 1

        # Count findings: look for severity headers
        critical = len(re.findall(r"\*\*(Critical|High)\*\*", session_text, re.IGNORECASE))
        medium = len(re.findall(r"\*\*Medium\*\*", session_text, re.IGNORECASE))
        # Conservative: count Critical+High as definite bugs, Medium as 50%
        total_findings += critical + (medium // 2)

        # Classify review mode
        if BRUTAL_INDICATOR_RE.search(session_text):
            modes["brutal"] += 1
        elif MULTI_INDICATOR_RE.search(session_text):
            modes["multi_persona"] += 1
        else:
            modes["single"] += 1

    return {"count": review_sessions, "findings": total_findings, "modes": modes}


def main() -> int:
    args = parse_args()
    repo = str(Path(args.repo_dir).resolve())

    try:
        subprocess.run(["git", "rev-parse", "--git-dir"], cwd=repo, capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        sys.stderr.write(f"FAIL: not a git repository: {repo}\n")
        return 1

    since_date = resolve_since_date(repo, args.since)
    commits = get_commits(repo, since_date)
    by_source = classify_commits(commits)

    log_dir = Path(args.log_dir) if args.log_dir else derive_log_dir(repo)
    review_data = scan_review_sessions(log_dir)

    # Add review-finding bugs from Claude sessions
    if review_data["findings"] > 0:
        by_source["review_finding"] = review_data["findings"]

    bugs_total = sum(by_source.values())

    # Estimate stage distribution — conservative heuristic
    # "code_review" = review_finding source; "in_dev" = fix_commit + subject_keyword (likely immediate);
    # "test_suite" = test-flavored keywords (crude); rest = unclassified
    by_stage: dict[str, int] = {
        "in_dev": by_source.get("fix_commit", 0) + by_source.get("subject_keyword", 0),
        "code_review": by_source.get("review_finding", 0) + by_source.get("bundled_fix", 0),
        "test_suite": 0,  # requires deeper analysis — set 0 and note in output
        "manual_qa": by_source.get("revert", 0),
        "production": 0,
        "escaped": 0,  # unknown without post-release data
    }

    review_detail = review_data["modes"]

    out = {
        "since_date": since_date,
        "commits_scanned": len(commits),
        "bugs_total": bugs_total,
        "by_source": by_source,
        "by_stage": by_stage,
        "code_review_detail": review_detail,
        "escaped_count": 0,
        "review_sessions_found": review_data["count"],
        "log_dir": str(log_dir) if log_dir else None,
        "note": (
            "by_stage.test_suite and by_stage.escaped require manual review — "
            "git commit messages alone cannot reliably distinguish test-caught from in-dev bugs, "
            "and escaped bugs are only knowable from post-release monitoring."
        ),
    }
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
