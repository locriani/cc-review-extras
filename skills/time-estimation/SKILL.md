---
name: time-estimation
description: Use when the user asks how many hours they've worked on a project/feature since a date, build, or commit — questions like "how long have I spent on X", "hours since build N", "time on Y this week". Do not use for pure git-log summaries or PR-activity recaps.
---

# Time Estimation

## Execution model — DELEGATE TO A SUBAGENT

**Do NOT do this work in the top-level session.** Time estimation reads multi-MB of jsonl session logs, parses git history, and produces a compact final artifact (a small table). That is the textbook subagent shape: messy bulky input → tiny clean output.

When this skill triggers in the top-level session, your job is to **dispatch a general-purpose subagent** and relay its result. Do not pull the data yourself.

### How to dispatch

Use the `Agent` tool with `subagent_type: "general-purpose"`. The subagent does NOT have access to this skill (personal `~/.claude/skills/` are not auto-loaded into subagents). You must inline the instructions.

Build the prompt as:

1. The user's exact original question (verbatim — do not paraphrase the project name, the date anchor, or the build number).
2. The working-directory hint (the project repo path) and the matching Claude Code log directory: `~/.claude/projects/<dir-slug-with-slashes-replaced-by-dashes>/*.jsonl`.
3. Whether the user asked for the hourly breakdown, the sources block, or both. If unsure, include both.
4. **Everything below the `## Subagent payload — instructions to inline` heading in this file**, copied verbatim into the prompt. That payload IS the skill content the subagent needs.

After the subagent returns, **relay its output verbatim** to the user. Do not re-format, re-summarize, or add commentary above or below the table — the artifact IS the response. The only exception: if the subagent flags an ambiguity (couldn't find the anchor commit, log directory empty, etc.), surface that question to the user.

### When NOT to delegate

Skip the subagent and answer inline only if BOTH:
- The user is asking a quick clarifying follow-up about a previous time-estimation answer (no new data fetch needed), AND
- You can answer purely from numbers already in this conversation.

Everything else: subagent.

---

## Subagent payload — instructions to inline

> Everything below this line is what the subagent needs. Copy it into the dispatch prompt.

You are answering a time-estimation question. Produce a **single best estimate** plus a tight **range**, backed by multiple data sources, and (if asked) a variable-size hourly breakdown that reads like a story.

The artifact is a **markdown table**. Not a paragraph. Not a chart. A table with a bold headline above it.

### Data sources (use all that apply, in this order)

1. **Git commit history** — `git log --since=<anchor>` clustered into work sessions. Treat any commit-time gap >2h as a session break. Watch for squash-commits where many builds land in a single timestamp burst — they hide multi-day work; flag and estimate the hidden span separately.
2. **Claude Code session logs** — `~/.claude/projects/<project-dir-slug>/*.jsonl`. Every event is timestamped (`.timestamp` field, ISO 8601). Compute "active time" by summing only the gaps between consecutive events ≤ a chosen idle threshold. Report at multiple thresholds:
   - ≤15 min — pure engaged time (Claude is the bottleneck)
   - ≤30 min — engaged time including test/build waits
3. **macOS unified log** (`log show`) — try Xcode launches, screensaver/loginwindow events. Often empty due to log eviction; note when it yielded nothing.
4. **File mtimes** in the repo — usually low signal (only last save survives). Note when checked.
5. **Shell history** (`~/.zsh_history`) — only useful if `EXTENDED_HISTORY` is set. Note when checked.

### Helper scripts (use these — don't reinvent)

Two scripts ship with this skill at `~/.claude/skills/time-estimation/scripts/`:

- **`claude-log-stats.py <project-dir> [--since YYYY-MM-DD]`** — outputs JSON with `event_count`, `first_event`, `last_event`, `active_hours_15m`, `active_hours_30m`, and `chapter_breaks` (idle gaps ≥15 min, the natural-chapter signal). Handles the project-path → log-dir slug translation. Returns `event_count: 0` and `first_event: null` if no logs cover the requested window.
- **`git-clusters.sh <repo-dir> <anchor> [--gap-minutes N]`** — outputs commits since `<anchor>` grouped into sessions (gaps > N min = new session, default 120). `<anchor>` accepts a commit SHA, branch name, ISO date, or relative phrase like "2 weeks ago".

Run them with `--help` for full usage. **Always invoke these instead of writing inline jq/python** — they handle edge cases (TZ-offset parsing, bare-date `--since` quirk, missing log dirs, empty event streams) that one-off snippets keep getting wrong.

### Log-coverage fallback (when Claude logs don't reach back to the anchor)

`~/.claude/projects/` retains session logs for a finite period. If `claude-log-stats.py --since <anchor>` returns `first_event` later than the anchor (or `event_count: 0`), the logs do NOT cover the full window. Don't refuse to estimate — calibrate from what you have:

1. **Compute the covered window's ratios** from logs that DO exist:
   - `active_hours_per_commit` = `active_hours_15m` / (commits in covered window)
   - `active_hours_per_day` = `active_hours_15m` / (days in covered window)
2. **Pick the calibration unit that fits.** Use per-commit when commit cadence is steady; per-day when commit sizes vary wildly.
3. **Project backward** by multiplying the calibrated rate by commits or days in the uncovered window.
4. **Always disclose the fallback in the sources block.** Add a row labeled `Claude logs (projected from N% coverage)` and widen the range. A fallback estimate has lower confidence — give a wider range and say so explicitly.
5. **Use commit-message inspection as a sanity check.** If the uncovered window contains commits that read like "Initial scaffolding" vs "Major refactor", note that the projection is rougher than the covered window's number suggests.

Example phrasing in the sources block:
| Source | Hours |
|---|---|
| Git commit history | 25–32 |
| Claude Code session logs (last 14 days, 60% coverage) | 10–14 |
| Claude Code session logs (projected from coverage ratio for prior 28 days) | 18–28 |
| **Best estimate** | **~30** |

Never silently treat partial coverage as full coverage — that produces low numbers users will trust and act on.

#### Per-commit LOC extrapolation

When Claude logs cover only a *subset of commits* in the window (rather than missing the early window entirely), calibrate hours-per-LOC from the covered commits and apply that rate to uncovered commits. This is finer-grained than the window-level fallback above.

**How:**

1. For each commit covered by Claude logs, attribute the active time spent on it: sum the engaged-time intervals (≤15 min gaps) whose timestamps fall between the previous commit and this commit. Pair with that commit's diff size: `git show --stat <sha>` → sum of insertions + deletions.
2. Compute a hours-per-LOC ratio per covered commit. Use the **median** ratio across covered commits (not the mean — outliers like docs-only or generated-code commits skew the mean).
3. For each uncovered commit, multiply its LOC by the median ratio to estimate hours.
4. Sum: `total = covered_active_hours + Σ(uncovered_loc × median_ratio)`.
5. **Disclose in the sources block.** Add a row labeled `Claude logs (N commits covered, M extrapolated by LOC)` and widen the range. State the median ratio used.

**Example.**

| Commit | LOC | Covered? | Active hours |
|---|---|---|---|
| ABC | 150 | yes | 1.5 (logs) |
| DEF | 250 | yes | 2.5 (logs) |
| GHI | 350 | no | 3.5 (extrapolated, ratio = 0.01h/LOC) |

**Caveats.** The ratio is only meaningful when commits are roughly the same *kind* of work — feature code vs. mass-rename vs. test scaffolding will have very different rates. If covered commits span widely different categories (e.g., a 1k-line generated migration next to a 50-line bug fix), bucket them by category and apply per-bucket ratios. If you can't bucket cleanly, fall back to the window-level `active_hours_per_commit` and widen the range further.

### Reconciling the numbers

- Claude-active time + non-Claude work (Xcode UI tests, archives, manual reviews, auth prompts) should reconcile with the git-derived range. If they don't, say so.
- Give a **single best estimate** and a tight **range**. Don't hedge with three competing numbers in the headline.
- **Engaged-time floor.** When ≥80% of commits since the anchor are about the feature in question (check commit messages), `active_hours_15m` is a **hard floor** for the best estimate. The estimate is `engaged_15m + non_Claude_work` — it is NEVER below `engaged_15m`. If your reconciliation produces a number below that floor, your reconciliation is wrong.
- **Squashed commits → don't reconcile against git.** If git clusters show ≥3 builds landing within a single ≤5-min commit burst, the git-derived hours are a known underestimate of the work behind those builds. Do **not** average Claude-log time with git time in this case. Use Claude logs as the primary signal and add an explicit "hidden span" line in the sources block estimating the squashed work from scope (count of new builds × typical-build-effort, or read the commits' diffs).

### Output format

#### Headline + table
- **Always use a table.** Even after the user says "no chart" — they mean hourly breakdown, not "drop the table."
- Markdown table, two or three columns max.
- Lead with one bold headline: `## X feature — N hours in` or `## X, last N days: ~N hours`.
- No emojis.
- No "shipping" / "shipped" language unless the user explicitly said a build was actually shipped. Bumping the build number is not shipping.

#### Hourly breakdown
- Use **variable-size blocks, up to 4 hours each**. Never make every block the same size — uniform blocks feel mechanical and hide the actual shape of the work.
- Let the work decide the block boundary: an absorbing bug might be a 3- or 4-hour block; a quick fix might be 1 hour; routine cleanup might be 2 hours. Mix them.
- **Do NOT use uniform 2-hour or 3-hour blocks.** The breakdown should read like a story with natural chapter lengths.
- **Include build numbers** in their own column when relevant. Use `—` when the work spans no specific build.
- Each row gets **≤5 words** of description by default. Up to ~10 words is allowed only for a single long absorbing chapter (3–4h block) where consolidation would lose the actual story. Be aggressive about merging adjacent thin rows.
- The row is a label, not a sentence. Strip narrative. Strip "the". Strip adjectives that don't carry information.
- Final row is whatever the latest state is — do NOT close with "Shipping" unless told.

#### Short single-session totals (under ~6 hours)

When the whole project is one continuous sitting, the "up to 4 hours" cap and the "feels like chapters" guidance need adapting — but you still don't fall back to uniform blocks. The natural-chapter unit just gets smaller.

**Find the chapter breaks anyway.** They're hiding in the data:
- **Idle gaps in the Claude log** ≥15 min are the strongest signal. Even in a 5h session there are usually 2–3 of them. Treat each as a chapter boundary.
- **Commit clusters** are the second signal. A burst of 2-3 commits within 30 min is one chapter; a lone commit after a 1h gap is its own chapter.
- **Theme shifts in commit messages** are the third signal. "Fix X bug" → "Add Y feature" is a boundary even if the commits are 20 min apart.

**Block-size rules for short sessions:**
- Default minimum block size is **30–45 minutes**. Cap at ~2 hours instead of 4 — a 5h project shouldn't have a single 4h block (that's 80% of the work in one row).
- **15 minutes is the absolute floor**, and it should appear ONLY if it has to — i.e., a single distinct chunk of work that genuinely cannot be merged into an adjacent block without misrepresenting it (e.g., a 15-min hotfix between two unrelated multi-hour blocks). 15-min blocks are also only allowed when **total session time < 6 hours**. If the total is ≥6 hours, round small blocks up into the neighbor — at that scale 15m is noise.
- A 15-minute row in a breakdown is a strong signal something exceptional happened in that quarter-hour. If you can't name that exceptional thing in the row's one-line description, don't use a 15-min block — merge it.
- Aim for **3–6 rows total**. Fewer than 3 → not really a breakdown; more than 6 → blocks are too small.
- It's fine to have one 30-min row next to a 2-hour row in the same table. That's the variable-size principle working.

**Real example:** a 5h Standard-Configs session showed Claude-log idle gaps at minute ~95 (18m), minute ~180 (32m, the biggest), and minute ~232 (18m). Mapped to commit clusters, that's 4 natural chapters: setup + first fix → drift routine + hook fixes → apply-all UX overhaul → drift routine semantic rewrite. Blocks of roughly 1h / 1h / 1.5h / 1.5h — variable, story-shaped, no uniform fallback.

#### Language
- Write for a non-programmer friend who's curious but not technical. Not 8th-grade-textbook simple, but accessible.
- Don't say "Built the core feature — letting you save your entire app's data into a single encrypted file and restore it later." Say "Built the backup feature out."
- Use real, specific words for bugs and wins: "restoring duplicated everything in iCloud", "race condition where two dialogs fought on screen", "eight serious issues found and fixed".
- No marketing fluff. No "robust". No "comprehensive".

#### Sources block (when verifiability is asked for)

A short table of sources with their estimates, plus a one-line "best estimate" row at the bottom:

| Source | Hours |
|---|---|
| Git commit history | 25–32 |
| Claude Code session logs | 13–18 |
| **Best estimate** | **~25** |

Then one sentence explaining the gap (e.g., "The gap is Xcode UI tests, archives, and manual review — checks out.").

### Process

1. Find the anchor commit (e.g., "since build 105 shipped") and its timestamp.
2. Pull `git log --since=<anchor> --pretty='%ai %s'` and read commit messages — they tell you what each block was actually about.
3. Compute Claude-log active time at multiple thresholds. Use python3 + json to parse `.timestamp` from each line of every `*.jsonl` in the log dir; sort all timestamps; sum gaps ≤ threshold.
4. Check the other sources, note which were empty.
5. Reconcile. Pick the best estimate. State the range.
6. If asked for a breakdown, map commits to variable-size blocks and pick the one most interesting thing per block.
7. **Incremental check.** Before outputting, look for prior time-estimation answers on the same feature in this project's recent Claude session logs (`~/.claude/projects/<slug>/*.jsonl`, grep for the feature name and `## .* — .* hours` headlines). If a prior answer exists with a stated number `X` hours from date `D`:
   - Run `claude-log-stats.py --since D` to get new active hours since the prior estimate.
   - Your new estimate must be **≥ X + new_engaged_hours_since_D** (when the feature still dominates new commits).
   - Surface the delta in the sources block, e.g.:

     | Source | Hours |
     |---|---|
     | Prior estimate (2026-05-03) | 27 |
     | New engaged hours since 2026-05-03 (≤15 min) | 13.4 |
     | New build/test waits since 2026-05-03 (≤30 min) | 17.2 |
     | **Best estimate** | **~40** |

8. Output in the format above. **Output only the artifact** (headline + table(s)). No preamble, no "here's your estimate", no closing remarks.

### Worked example (Vendle backup feature, 27 hours since build 105)

Note the variable block sizes (1h, 4h, 2h, 3h, 3h, 2h, 4h, 1h, 3h, 4h), the build-number column, the ≤5-word row rule, and no "shipping" close.

```markdown
## Vendle backup feature — 27 hours in

| Hours | Build | |
|---|---|---|
| 1 | 105 | Fixed file-save permissions. |
| 2–5 | 106–110 | Built encrypted backup feature. |
| 6–7 | 111–112 | Hardened import pipeline. |
| 8–10 | — | Locked file format with tests. |
| 11–13 | 113–116 | Fixed iCloud duplication bug. |
| 14–15 | 117 | Code review fixes. |
| 16–19 | 118 | First end-to-end UI test. |
| 20 | — | Squashed dialog race. |
| 21–23 | 119 | Regression test for iCloud bug. |
| 24–27 | 119 | Pre-flight checks, snapshot recovery. |
```

Underlying numbers behind that estimate:
- Git: 31 commits since the build-105 ship commit, clustered into ~10 work sessions
- Claude Code logs: 5,285 events; active time 14.1h (≤15m gaps) / 18.8h (≤30m gaps)
- Reconciliation: ~14–19h Claude-active + ~8–13h non-Claude (Xcode UI test runs, manual reviews, archives) = ~27h

### Don'ts

- Don't open with "Shipped N builds" — that framing isn't wanted.
- Don't pad with explanation paragraphs around the table. The table is the artifact.
- Don't use emojis even when it would be cute.
- Don't claim "Shipping" at the end of the breakdown.
- Don't call something a feature "release" or "ship" prematurely.
- Don't use uniform 2-hour or 3-hour blocks across the whole breakdown.
- Don't use seniority or role framing in row descriptions ("staff engineer", "senior dev", "lead architect") — describe the work, not the persona.
- Don't produce a best-estimate below `active_hours_15m` when commits are dominantly about the feature. That violates the engaged-time floor.
- Don't average Claude-log hours with git-cluster hours when git has squashed-commit bursts — the git number is artifactually low; using it pulls the answer down.
