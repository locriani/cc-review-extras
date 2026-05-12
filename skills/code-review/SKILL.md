---
name: code-review
description: Use when the user asks for a code review of recent changes, a PR, a diff, a worktree, or "review what I just did" — including phrases like "review this", "code review", "self-review", "review my changes", "review the diff", "what's wrong with this". Do NOT use for one-line typo/comment/config changes (review inline) or for design feedback that hasn't been turned into code yet.
---

# Code Review

User-initiated code review with four dispatch modes:
1. **Single Senior Code Reviewer subagent** — the default for non-trivial changes (template at `code-reviewer.md` next to this file).
2. **Persona-axis dispatch** — escalation when the change is large, multi-module, or architecturally complex. Selects relevant personas from the catalog (see `CODE_REVIEW.md`) and dispatches one agent per persona.
3. **Named panel (7- or 9-persona)** — fixed composition for user-requested or auto-suggested deep reviews.
4. **Brutal panel** — all catalog personas; user-triggered only.

Plus local triage rules layered on top of the standard Critical/Important/Minor severity scheme — most importantly the **tests-that-lie** rule (gameable gates get fixed FIRST regardless of severity).

---

## Step 0 — Pre-review data gathering (non-trivial changes only)

Skip for trivial changes (§1 below). For all others, run these three scripts **before
dispatching any reviewer**. Their JSON output feeds directly into reviewer prompts as
objective data — not as a replacement for judgment.

Scripts are at `skills/code-review/scripts/` relative to the plugin root (typically
`~/.claude/skills/code-review/scripts/`). Require Python 3.9+ and `git` on PATH.

### 1. Hotspot analysis

Ranks files by churn × complexity — the most failure-prone files in the diff.

```bash
python3 ~/.claude/skills/code-review/scripts/hotspot.py <repo-dir> \
  [--since <anchor>] [--top 20] [--exclude <glob>]
```

Use output to:
- Highlight the top hotspot files in each reviewer's prompt ("file X has hotspot_score
  8.4 — treat it as highest risk").
- Set reviewer skepticism level: hotspot files get extra scrutiny in the prompt.

### 2. Diff surface characterization

Quantifies the review surface: LOC by category, test/source ratio, complexity delta.

```bash
python3 ~/.claude/skills/code-review/scripts/diff_surface.py <repo-dir> \
  [--base <SHA>] [--head <SHA>]
```

Use output to:
- Confirm or override the §3 escalation threshold: `files_changed > 5` or
  `loc_added > 500` → escalate to persona-axis dispatch.
- Flag test coverage gaps: `test_source_ratio < 0.5` → include as an explicit concern
  in the Staff Engineer (persona 2) and Devil's Advocate (persona 4) prompts.
- Include `complexity_delta` in reviewer prompts when it is large and positive (> 100).

### 3. Temporal coupling

Finds files that change together without explicit code dependencies — hidden coupling.

```bash
python3 ~/.claude/skills/code-review/scripts/coupling.py <repo-dir> \
  [--since <anchor>] [--min-support 3] [--top 30]
```

Use output to:
- Add high-risk pairs to the Architect (persona 1) prompt as potential hidden
  dependencies to examine.
- Include "medium" and "high" pairs that overlap with the diff in the Staff Engineer
  (persona 2) prompt as callsite concerns.

### When to skip Step 0

- Trivial change (§1): skip entirely.
- New repo or shallow clone (no history): scripts return empty results — proceed without
  them and note the gap in reviewer prompts.
- Single-file rename or pure move: `diff_surface.py` alone is sufficient; skip hotspot
  and coupling.

### Injecting data into persona prompts

After collecting script output, prepend a `## Pre-review data` block to each persona's
prompt with: top-5 hotspot files (path + score), diff surface summary
(`test_source_ratio`, `complexity_delta`, `files_changed`, `loc_added`), and any
high/medium coupling pairs that overlap with files in the diff.

---

## Decision tree

When this skill triggers, walk this tree:

### 1. Trivial change → review inline, no dispatch

ALL of:
- <1 file AND <50 lines.
- Typo fix, single-line config, comment edit, or trivially-obvious bug fix.
- No architectural or security implications.

Action: read the diff, give your assessment in the conversation. No subagent.

### 2. Default case → single-reviewer subagent

For most non-trivial changes:

1. Build the prompt from the template at `code-reviewer.md` next to this SKILL.md (resolve via the same plugin-cache path your other skill files use). Read it via the `Read` tool.
2. Fill the four placeholders: `{DESCRIPTION}` (brief summary of what was built), `{PLAN_OR_REQUIREMENTS}` (path to plan or restated requirements), `{BASE_SHA}` (`git rev-parse HEAD~1` or merge base), `{HEAD_SHA}` (`git rev-parse HEAD`).
3. Dispatch via `Agent` tool with `subagent_type: "general-purpose"`.
4. Receive Strengths / Issues (Critical/Important/Minor) / Recommendations / Assessment. Apply per the "Act on feedback" rules below.

Apply the local triage rules during fix triage — most importantly the **tests-that-lie** rule. See "Local triage rules" below.

### 3. Escalation → persona-axis dispatch

Switch to persona-axis dispatch (per `CODE_REVIEW.md`) when ANY of:

- **Diff > 500 lines** (rough proxy — a single reviewer struggles to keep multiple concerns in mind at this scale).
- **Touches >5 files** across multiple modules / layers.
- **Architectural change** — new modules, layer reorganization, dependency-direction changes, breaking API contract changes.
- **User-facing surface + backend logic in the same diff** (different concerns, different reviewer specializations).
- **Migration / schema change** under concurrent writes — needs a dedicated database axis.
- **Network-facing or security-sensitive code** — needs adversarial coverage.
- **User explicitly requests** a thorough / deep / multi-perspective review (but not a named panel — that's §4).

**Personas are the axes.** Select relevant personas from the catalog (personas 1–15 — Steve Jobs excluded from this mode). Always include:

- **Architect (1)** + **Staff Eng (2)** — always present.

Then add by change type:

| Change type | Default additions | Optional |
|---|---|---|
| Bash/shell patch | Data Analytics (3), Chaos Demon (5) | Sandi Metz (10) |
| Library code (no UI) | Devil's Advocate (4), Chaos Demon (5), Sandi Metz (10) | {Arch} Expert (11) |
| Feature with UI | UX Eng (6), UX Designer (7) | Sandi Metz (10) |
| Any repo with declared architecture | {Arch} Expert (11) | — |
| Concurrent code | Concurrency Expert (13) | — |
| Database / schema | Database Expert (15) | — |
| Distributed / networked state | Distributed Systems Expert (14), Database Expert (15) | — |
| Migration under concurrent writes | Database Expert (15), Chaos Demon (5) | Distributed Systems (14) |
| Network / security-sensitive | Chaos Demon (5), Devil's Advocate (4) | — |
| Observability concern | Data Analytics (3) | — |

**{Architectural Choice} Expert (11):** Read the repo's `CLAUDE.md`, `README.md`, or architecture docs to identify the declared architecture style. Name the persona accordingly:
- Clean Architecture → dispatch as **"Uncle Bob"** (Robert C. Martin's lens: strict layer enforcement, dependency rule, use-case-centric design).
- Other styles → "{Style} Expert" (e.g., "MVVM Expert", "Event Sourcing Expert", "Hexagonal Architecture Expert").
- If undeclared, infer from dominant code patterns and state your inference in the agent's prompt.

When escalating, follow `CODE_REVIEW.md` for:
1. **Persona catalog** — full definitions, primary lenses, persona-specific checks.
2. **Prompt-writing rules** — each agent's prompt MUST include explicit scope, absolute file paths, spec restated, numbered checks, skepticism demanded, severity-tagged output, word-count cap.
3. **Dispatch** — all persona-agents in ONE message (one tool-call block, multiple `Agent` tool uses). Sequential dispatch defeats the wall-clock-saving purpose.
4. **Aggregate findings, triage, fix, summarize.** See "Aggregation" below.

### 4. Named dispatch → fixed persona panel

When the user explicitly requests a named panel, or auto-suggestion criteria apply:

| Mode | Trigger phrases | Auto-suggest when |
|---|---|---|
| 7-persona | "7-persona review", "deep review", "full review panel", "review with all personas" | Final step in verification workflow (Block C) |
| 9-persona | "9-persona review", "9-axis review", "review with docs" | Diff touches any user-visible surface, public API contract, or doc file |
| Brutal panel | "brutal review", "full panel", "nuclear option", "brutal panel" | Never auto — user-triggered only |

Named panels dispatch all assigned personas in ONE message. Full persona definitions, checks, and panel compositions in `CODE_REVIEW.md`.

Note: "12-persona review" is a legacy alias for the brutal panel — use "brutal panel" / "brutal review" as the canonical terms.

---

## Local triage rules

After findings are in (single-reviewer or aggregated from persona-axis or named-panel dispatch), apply triage:

1. **Tests that lie come FIRST.** If any finding flags a test that passes when it shouldn't (fixture next to code under test that gets reflexively updated together, assertion on a flag the test sets, vacuous property generator), fix that **before** any other Critical/Important issue. Tests-that-lie produce false safety — green means ship, and you ship the bug. Reviewer heuristic for spotting one: "what's the smallest change that should fail this test but won't?"
2. **Act on severity.** Critical → fix immediately. Important → fix before proceeding. Minor → note for later.
3. **For dispatches mapping `CODE_REVIEW.md` severity** (Critical/High/Medium/Low/Nit) **to Critical/Important/Minor:** Critical+High → Critical. Medium → Important. Low+Nit → Minor.
4. **Verify the fix actually closes the finding.** Re-run relevant tests. For "test could be defeated" findings, inject the failure mode and confirm the test now catches it — otherwise you've fixed nothing.
5. **Track deferred findings explicitly.** A finding deliberately punted lives in CHANGELOG or as a `decision`-tagged memory (per `## ai-memory MCP` directive in CLAUDE.md) — not as a comment that quietly evaporates.

---

## Aggregation (persona-axis and named-panel dispatch)

When all persona-agents return:

1. Apply the local triage rules above.
2. Fix the real findings. Skip false positives without arguing.
3. Re-run relevant tests after each fix.
4. Build a structured summary using the standard output format, with personas called out:

```
## Code review summary

**Mode:** [Persona-axis dispatch | 7-persona | 9-persona | Brutal panel]
**Personas dispatched:** <list>

### Strengths
[from agents' acknowledgments — distinct items, no duplicates]

### Issues

#### Critical (Must Fix) — all fixed
- [<persona>] <file:line>: <what was wrong> → <fix that landed>

#### Important (Should Fix)
- [<persona>] <file:line>: ... → <fix or "deferred — see <CHANGELOG.md|memory:<id>>">

#### Minor (Nice to Have)
- [<persona>] <file:line>: ... (skipped — not in open files)

#### Tests-that-lie — fixed FIRST
- [<persona>] <file:line>: <why the test was vacuous> → <fix> → verified by <how>

### Assessment

**Ready to merge?** [Yes | No | With fixes — listed above]

**Reasoning:** [1-2 sentence technical assessment, mentioning whether all personas returned clean]
```

Don't dump full agent reports into main context — they were used to derive fixes; the fixes themselves are the artifact.

---

## Red flags — STOP and dispatch

If you catch yourself thinking any of these, dispatch the reviewer (or escalate to persona-axis dispatch) — do **not** review inline:

- "It's small enough — I'll just read through it."
- "I already reviewed as I wrote it."
- "Tests pass, that's enough."
- "The user is in a rush."
- "I'll review at PR time, this is just a WIP commit."
- "Nothing here is architecturally significant."
- "The diff is medium — single reviewer is fine."

The trivial-change escape hatch (§1 above) is the ONLY case inline review is allowed. It requires **all three** conditions (file count, line count, no architectural/security implications) — match all, or dispatch.

## Common rationalizations and the reality

| Rationalization | Reality |
|---|---|
| "Diff is small, I can eyeball it" | "Small" is not the rule. <1 file AND <50 lines AND no architectural/security implications is the rule. Match all three or dispatch. |
| "Medium diff, single reviewer is fine" | Medium-sized diffs that touch >5 files or cross UI/backend boundaries are the exact escalation case. Persona-axis dispatch selection (table above) is mandatory, not optional. |
| "Tests pass, the review is redundant" | Reviewers catch what tests can't: design fit, reuse, observability, tests-that-lie. Green tests + bad design ships bad design. |
| "The reviewer will repeat what I already know" | Then the prompt is wrong. Self-contained, persona-scoped prompts per CODE_REVIEW.md yield findings you don't already know. |
| "Bundling personas into one agent saves tokens" | Bundled prompts dilute focus and produce shallow reports. One persona per agent — no exceptions. |
| "The user explicitly said 'quick review'" | "Quick" describes turnaround, not depth. Dispatch normally; the subagent can return fast. |
| "I don't need the {Arch} Expert — the code obviously follows the architecture" | The {Arch} Expert's job is to find the one layer crossing that's 'obviously fine.' Declare your inference in the prompt and let the agent verify it. |
| "I don't need 9-persona, the code doesn't touch docs" | If ANY user-visible surface changed, the User Documentation Expert will find a doc/UI mismatch you won't. One extra agent, zero extra wall-clock cost. |
| "Brutal panel is overkill" | That's often true. Reserve it for high-stakes diffs. If you're not sure this qualifies, it doesn't — use 9-persona or 7-persona. |

## Hard rules

- **Never skip review because "it's simple"** (beyond the trivial-change escape hatch in §1).
- **Ignore Critical issues:** never. **Proceed with unfixed Important issues:** never.
- **Don't argue with valid technical feedback.** Push back only with technical reasoning + code/tests that prove the reviewer wrong.
- **Never do a code review yourself in main context** when the diff touches >1 file or >50 lines. Delegate. Aggregate. Fix. Then summarize.
- **One persona per agent** when running persona-axis or named-panel dispatch — do not bundle two personas into a single agent.
- **Build before reviewing.** Never dispatch reviewers against a change that doesn't compile.
- **Self-contained prompts.** Each agent gets the full diff/context it needs.

For the persona catalog, prompt-craft details, and named-panel compositions, see `CODE_REVIEW.md` next to this file.
