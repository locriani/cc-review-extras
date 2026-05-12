---
name: dev-velocity
description: Use when the user asks about code output rate — "how many lines per hour", "LOC per commit", "how fast am I writing code", "velocity metrics", "lines of code stats", "how productive am I", "LOC rate", "code throughput". Do NOT use for time estimation (use time-estimation skill), bug counts (use defect-density skill), or general git history summaries.
---

# Dev Velocity

Measures code output rate: LOC/hour, hours/LOC, and LOC/commit. Subagent-dispatched — bulky git data → compact metric table.

## Execution model — DELEGATE TO A SUBAGENT

Do NOT do this work in the top-level session. Parsing `git log --stat` across a full repo history is bulky. Dispatch a `general-purpose` subagent and relay its result verbatim.

When this skill triggers in the top-level session, your job is to dispatch a subagent. Copy everything below `## Subagent payload` into the prompt along with:
1. The user's original question verbatim
2. The repo path
3. The Claude Code log dir: `~/.claude/projects/<dir-slug>/*.jsonl`
4. Any hours estimate already established in-context (from a prior time-estimation run this session) — pass it as `--hours <N>` to skip re-estimation

After the subagent returns, relay its output verbatim. No reformatting, no preamble.

### When NOT to delegate
Skip the subagent only if the user is asking a follow-up about numbers already in this conversation (no new data fetch needed). Everything else: subagent.

---

## Subagent payload — instructions to inline

You are answering a dev-velocity question. Compute code output rate metrics for a project and present them as a markdown table.

### Metrics to compute

| Metric | How |
|---|---|
| **LOC/hour** | (net LOC added) / (hours of active development) |
| **Hours/LOC** | inverse; express in seconds for readability |
| **LOC/commit** | (net LOC added) / (commit count) |

"Net LOC added" = total insertions from `git log --stat` (not gross lines typed; deletions are separate). If the user asks for gross churn (insertions + deletions), add that as a second row.

### Getting LOC from git

Use the helper script at `~/.claude/skills/dev-velocity/scripts/loc-stats.py` (see below). If not present, run manually:

```bash
git -C <repo> log --since=<anchor> --stat --pretty=tformat: | \
  awk '/insertion|deletion/ {for(i=1;i<=NF;i++) if($i~/insertion/) ins+=$(i-1); if($i~/deletion/) del+=$(i-1)} END {print "ins="ins, "del="del}'
```

Always pass `--exclude` globs for auto-generated files (e.g., `*.pb.swift`, `*.generated.*`, `*.xcassets`, `*.strings` unless user asks for them). These inflate LOC without representing engineering work.

### Getting hours

**Prefer in-context hours.** If time-estimation was run earlier this conversation and an hours estimate is in context, use it — do not re-run the estimation. Pass it as the hours denominator directly.

If hours are not in context: run `claude-log-stats.py <repo> [--since ANCHOR]` and use `active_hours_15m` as the denominator. Note in the output which source was used.

### Squash-commit detection

Squash-merge workflows produce artificially high LOC/commit. Detect this:
- Run `git log --since=<anchor> --format="%ai %s"` and look for ≥3 commits within a ≤5-minute window with sequential build numbers in their subject lines.
- If detected: flag the LOC/commit row with `*squash workflow — effective per-branch-commit is Nx lower` and compute the adjusted per-intermediate-commit estimate if you can (branch count × typical commits per branch from git history).

### Contextual comparison

Report the user's numbers against these research-backed baselines, with honest framing:

| Baseline | LOC/hr | Source |
|---|---|---|
| Non-trivial senior dev (industry research) | 10–50 | Brooks, McConnell, Jones |
| Boilerplate / scaffolding work | 50–200 | Practitioner estimates |
| Claude-assisted, high churn | varies widely | Dependent on task mix |

**Important:** Do NOT present 100–150 as a research-backed "senior dev" figure — it has no primary source. The Brooks/McConnell/Jones data consistently puts the upper end for non-trivial delivered code at ~50 LOC/hr on small-to-medium codebases. Claude-assisted rates of 500–2,000+ LOC/hr are plausible on scaffolding-heavy features but reflect a very different unit of work than unaided engineering.

### Output format

Lead with a bold headline: `## <Project> velocity — <anchor> to <date>`.

Primary table (always):

| Metric | Value | Notes |
|---|---|---|
| LOC added | N | excludes generated files |
| Active hours | N | Claude logs, ≤15m gaps |
| LOC / hour | N | |
| Seconds / LOC | N | = 3600 / (LOC/hr) |
| LOC / commit | N | *squash-adjusted if applicable |
| Commits | N | |

Comparison table (always):

| Context | LOC/hr |
|---|---|
| This project | N |
| Senior dev, non-trivial work (research) | 10–50 |
| Boilerplate-heavy work | 50–200 |

No preamble, no closing remarks. Table is the artifact.

### Don'ts
- Don't claim 100–150 LOC/hr is a research-backed industry average — it isn't.
- Don't include generated code (`.pb.*`, `.xcassets`, `*.generated.*`) in the count without flagging it.
- Don't present LOC/hr as a quality metric or a goal to optimize — it isn't.
- Don't conflate gross churn (insertions + deletions) with net LOC added unless explicitly asked.

---

### Red flags — common rationalizations

| Thought | Reality |
|---|---|
| "Higher LOC/hr = more productive" | LOC measures output volume, not value. Deleting 1,000 lines of dead code is high-value, zero LOC/hr. |
| "The senior dev baseline is 100–150 LOC/hr" | No primary source. Brooks says 10 lines/day (shipped, debugged). McConnell says 2–16/hr for non-trivial work. |
| "I'll skip excluding generated files — it's faster" | Generated files can add 10–100× artificial LOC. The number becomes meaningless without the exclusion. |
| "LOC/commit is too high — the project is unhealthy" | Large LOC/commit often just means squash workflow, not low commit discipline. Check before concluding. |
