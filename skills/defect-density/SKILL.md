---
name: defect-density
description: Use when the user asks about bug rates — "how many bugs per hour", "defect rate", "bug density", "how many bugs have I introduced", "escaped bugs", "bugs per LOC", "defect injection rate", "what's my bug rate", "how many bugs made it to production", "where are my bugs coming from". Do NOT use for general git summaries or time estimation.
---

# Defect Density

Measures bug introduction rate and where bugs were caught. Subagent-dispatched — bulky multi-source data → compact metric table.

## Execution model — DELEGATE TO A SUBAGENT

Do NOT do this work in the top-level session. Dispatch a `general-purpose` subagent with the instructions below and relay its result verbatim.

When this skill triggers, dispatch a subagent with:
1. The user's original question verbatim
2. The repo path
3. The Claude Code log dir: `~/.claude/projects/<dir-slug>/*.jsonl`
4. Any hours estimate already in-context from time-estimation
5. Everything below `## Subagent payload`

After the subagent returns, relay its output verbatim.

---

## Subagent payload — instructions to inline

You are answering a defect-density question. Tally bugs introduced, how they were caught, and compute a defect rate. Output a markdown table — the table is the artifact.

### Bug sources — cast a wide net

Do NOT rely only on `fix:` commit prefixes. Bugs appear in many commit shapes. Tally from ALL of the following:

#### 1. Conventional-commit fix subjects
```
git log --pretty="%H %s" | grep -iE "^[a-f0-9]+ fix(\(.*\))?:"
```
Each is one bug unless the commit body lists numbered actions (see §Bundled fixes).

#### 2. Other subject-line patterns indicating a bug fix
Search for subjects containing (case-insensitive): `bug`, `bugfix`, `hotfix`, `patch`, `revert`, `regression`, `repair`, `broken`, `wrong`, `incorrect`, `typo`, `off-by-one`, `nil crash`, `crash`, `invalid`, `missing`, `forgot`, `oops`, `accidentally`, `unintentional`, `race condition`, `deadlock`, `leak`, `overflow`.

```
git log --pretty="%H %s" --since=<anchor> | grep -iE \
  "bug|bugfix|hotfix|patch|revert|regression|repair|broken|wrong|incorrect|typo|off.by.one|crash|invalid|missing|forgot|oops|accidentally|unintentional|race.condition|deadlock|leak|overflow"
```

**Important:** Filter out false positives — commits like "add missing feature" or "fix typo in README" are often not bugs. Read the commit body for ambiguous cases.

#### 3. GitHub-style issue-closing keywords in commit body
```
git log --pretty="%H%n%B%n---" --since=<anchor> | grep -iE "closes? #|fixes? #|resolves? #"
```
Each unique issue number is one bug.

#### 4. Bundled fix commits
Some commits bundle multiple individual fixes. Detect these by reading the body for:
- Numbered lists: "1. Fix X\n2. Fix Y\n3. Fix Z"
- Patterns like "land actions 1–11", "address 5-agent findings", "address N review comments"
- "Fix the following: ..."

For bundled commits: **count the individual items**, not the commit. Read the body. If it says "land actions 1–11" and item 3, 5, 7, 9 are bug fixes (vs. style/refactor items), count those 4, not 11.

#### 5. Review-finding commits from Claude logs
Grep Claude session `.jsonl` logs for review sessions:
```
grep -h "review findings\|critical\|high\|medium\|important" ~/.claude/projects/<slug>/*.jsonl
```
Look for assistant messages that list review findings with severities. Extract:
- Count of **Critical** and **High** findings that were fixed (these are bugs)
- Count of **Medium** findings that were fixed (may or may not be bugs — use judgment)
- Note which review mode was used: single reviewer, multi-persona panel (N personas), or brutal (all personas)

Each distinct finding that represents a behavioral defect (not a style issue) is one bug caught by code review.

#### 6. Test-failure-driven fixes
Commits that mention test failures, CI fixes, or "red → green":
```
git log --pretty="%H %s" --since=<anchor> | grep -iE "test|ci|failing|red|green|assert|flak"
```
Read these to determine if they fixed a defect vs. updated tests for new behavior. Defect fixes count; test updates for intentional behavior changes do not.

#### 7. Revert commits
```
git log --pretty="%H %s" --since=<anchor> | grep -iE "^[a-f0-9]+ revert"
```
Each revert is almost always a bug (the reverted code was wrong). Count as one bug.

### Classifying where bugs were caught

For each bug, determine where it was caught:

| Stage | Indicators |
|---|---|
| **In-dev** | Fix commit immediately follows the introducing commit (same session), test failure caught it before review, commit message says "oops", "forgot", "missed" |
| **Code review** | Review-finding commit, "address review comments", "land actions N–M", "address N-agent findings"; link to review session in Claude logs |
| **Test suite** | CI failure, test-name in commit subject, "red → green" |
| **Manual QA / TestFlight** | Build-numbered hotfix commit after a TestFlight release; commit message references a build number that's already been distributed |
| **Production / customer** | Rarely visible in commits; look for "reported by", "customer found", or commits that reference production incidents |
| **Escaped** | Bugs in the introducing commit that have NO subsequent fix commit in-range. These are candidates for escaped bugs — flag them but acknowledge uncertainty (the bug may be fixed in a future commit outside the range, or may be undetected). |

### Output format

Lead with: `## <Project> defect density — <anchor> to <date>`

**Primary metrics table:**

| Metric | Value |
|---|---|
| Total bugs identified | N |
| Hours of development | N (or "not provided") |
| Bugs / hour | N (or "—") |
| Bugs / KLOC | N (or "—") |
| Bugs caught before release | N (%) |
| Estimated escaped bugs | N (%) |

**Bug escape funnel table** (always include):

| Stage | Bugs caught | % of total |
|---|---|---|
| In-development (immediate fix) | N | % |
| Code review — single reviewer | N | % |
| Code review — multi-persona panel | N | % |
| Code review — brutal (all personas) | N | % |
| Test suite | N | % |
| Manual QA / TestFlight | N | % |
| Production / customer report | N | % |
| **Total caught** | **N** | **%** |
| Estimated escaped | N | % |

Omit rows with zero counts (keep the table clean). If code review data is unavailable (no Claude review sessions found), note that in a footnote rather than leaving zeros.

**Industry context: defect density (bugs/KLOC)** (always include):

| Context | Bugs/KLOC | Phase | Source |
|---|---|---|---|
| This project | compute | see primary table | — |
| Industry average | 15–50 | at release | McConnell, *Code Complete* |
| Industry average | 0.5–10 | post field-hardening | McConnell |
| Microsoft at release | ~10–20 | during internal testing | McConnell |
| Microsoft shipped | ~0.5 | after field hardening | McConnell |
| NASA / safety-critical | <0.1 | at release | SEI/CMU |
| Best-in-class teams (target) | <1 | at release | Jones, industry practitioners |

**Industry context: defect removal efficiency (DRE)**:

| Context | DRE | Source |
|---|---|---|
| This project | compute | see escape funnel |
| U.S. industry average (2016) | ~92.5% | Jones, 13k+ projects |
| Best-in-class teams | 99%+ | Jones |
| Any single technique alone (max) | ~65–68% | Jones, per-technique data |
| Unit tests alone | ~25–30% | Jones |
| Formal code inspection alone | ~65% | Jones |

**Industry context: bugs/hour (derived range, not a primary research metric)**:

The research literature uses bugs/KLOC, not bugs/hour. A bugs/hour figure can be derived by multiplying an injection rate by an output rate, but since both vary widely, treat this as a rough orientation only.

| Context | Bugs/hr (pre-removal) | Derivation |
|---|---|---|
| Senior dev, non-trivial work | ~0.1–0.5 | 10–50 LOC/hr × ~100 bugs/KLOC pre-QA (McConnell) |
| Boilerplate / scaffolding | ~0.5–2 | 50–200 LOC/hr × same injection rate |
| Junior dev | ~0.3–1.5 | 2–3× higher injection rate per LOC (Jones) |
| Best-in-class (TDD + inspections) | ~0.02–0.1 | ~80% reduction in injection rate vs. average |

The pre-removal 100 bugs/KLOC figure (McConnell) represents defects before any QA pass; delivered code averages 15–50/KLOC. So the "bugs introduced per hour" that survive to release is roughly **5–10× lower** than the pre-removal rate above.

If the project's bugs/hour lands in the 0.1–0.5 range, that is consistent with the senior-dev pre-removal baseline and suggests the review/test pipeline is doing most of the removal work before release.

### Rate calculations

Only compute rates if hours and/or LOC are available:

- **Bugs/hour** = total bugs / hours. Requires hours from time-estimation. Note whether hours are "active hours (≤15m)" or estimated total.
- **Bugs/KLOC** = total bugs / (net LOC / 1000). Compare against the bugs/KLOC table above, and note the measurement point (pre-release vs. post-release).

If the project's bugs/KLOC is well below 15 at release, note it — that is either a sign of strong review/test practices (high DRE) or an incomplete tally. Check the escape funnel to distinguish.

### Helper script

Use `~/.claude/skills/defect-density/scripts/bug-tally.py` to automate the git parsing. Pass its JSON output into your analysis.

### Don'ts
- Don't count only `fix:` commits — that misses 50–70% of bugs typically.
- Don't present the "0.4 bugs/hour" figure from conversation context as an industry benchmark — it was a project-specific calculation.
- Don't omit the funnel table — WHERE bugs were caught is the most actionable output.
- Don't call escaped bugs "zero" unless you've confirmed there are no post-release hotfixes AND the project has no open bug reports.
- Don't count style-guide violations or refactor suggestions from code review as bugs.
- Don't penalize bundled review-finding commits by counting them as 1 bug — read the body and count items.

---

### Red flags — common rationalizations

| Thought | Reality |
|---|---|
| "I'll just grep for fix: commits" | Misses hotfixes, reverts, bundled review findings, test-driven fixes, and plain-english descriptions. Under-counts by 2–5×. |
| "Low bugs/hour means I write good code" | Maybe. Or you have light review coverage and bugs are escaping. The escape rate matters more than the raw count. |
| "My DRE is 100% because nothing escaped" | Only knowable if you have explicit production monitoring. Absence of evidence is not evidence of absence. |
| "Jones's numbers don't apply to me — I use AI" | The research predates AI-assisted dev. Your escape funnel data is more trustworthy than the benchmarks; use them as context, not gospel. |
| "The bugs/KLOC seems too low, maybe I miscounted" | More likely: you counted only fix: commits. Re-run with the full source taxonomy. |
