# Code Review Discipline — Persona Catalog and Dispatch Rules

Whenever you perform a code review, it MUST be done by dispatching persona-agents in parallel — one per persona — in a single message. The main context aggregates findings; it does not do the review itself.

---

## Pre-review scripts

Run these before dispatching reviewers. They produce JSON that you inject into reviewer
prompts as objective data. See `SKILL.md §Step 0` for invocation details.

| Script | Purpose | Key output fields to inject |
|---|---|---|
| `hotspot.py` | High-churn × high-complexity files | `files[].hotspot_score`, `files[].path` |
| `diff_surface.py` | Diff surface breakdown | `test_source_ratio`, `complexity_delta`, `files_changed`, `loc_added` |
| `coupling.py` | Temporal coupling pairs | `pairs[].coupling_strength`, `pairs[].implied_risk`, `pairs[].file_a/b` |

**Injecting into persona prompts:** prepend a `## Pre-review data` block to each persona's
prompt listing the top-5 hotspots, the diff surface summary, and any high/medium coupling
pairs that involve files touched by the diff. Reviewers use this to calibrate effort and
focus skepticism where risk is highest.

---

## Persona catalog

Every review mode draws from this catalog. Personas are orthogonal by primary-lens design — each agent is explicitly scoped to its lens and told not to drift into adjacent ones.

### Core team (personas 1–7) — always the foundation

Used in 7-persona, 9-persona, brutal panel, and as the baseline for persona-axis dispatch.

| # | Persona | Primary lens |
|---|---|---|
| 1 | **Senior Architect** | Structural correctness, layer boundaries, dependency direction, extensibility |
| 2 | **Senior Staff Engineer** | Implementation quality, edge cases, error handling, maintainability, "what breaks Friday night" |
| 3 | **Data Analytics Engineer** | Observability, log structure, metric emission, debuggability of failures |
| 4 | **Devil's Advocate** | Challenges every design decision — "why is this the right abstraction?" |
| 5 | **Chaos Demon** | Adversarial failure modes — malformed inputs, resource exhaustion, cascading failures |
| 6 | **UX Engineer** | API ergonomics, error-message quality, cognitive load of the happy path |
| 7 | **UX Designer** | Mental model, documentation match, discoverability |

### Documentation layer (personas 8–9) — 9-persona adds

| # | Persona | Primary lens |
|---|---|---|
| 8 | **Engineering Documentation Expert** | Code-level doc accuracy — lying docstrings, undocumented public APIs, orphaned TODOs |
| 9 | **User Documentation Expert** | User-facing doc completeness — changelogs, help pages, UI element coverage |

### Specialist pool (personas 10–15) — optional in persona-axis dispatch; included in brutal panel

| # | Persona | Primary lens |
|---|---|---|
| 10 | **Sandi Metz** | SOLID violations + over-engineering, premature abstraction, speculative features — practical OOP design instincts, POODR-style |
| 11 | **{Architectural Choice} Expert** | Dynamic persona — "Uncle Bob" for Clean Architecture, "{Style} Expert" for others. Finds layer crossings, pattern violations, bypasses of canonical flow. |
| 12 | **AI-pilled coworker** | Where hand-rolled logic should be AI-driven; prompt engineering quality; AI workaround proportionality |
| 13 | **Concurrency Expert** | Thread safety, race conditions, lock ordering, structured vs. unstructured async, actor/goroutine correctness |
| 14 | **Distributed Systems Expert** | Consistency guarantees, idempotency, partition tolerance, CAP tradeoffs, distributed transaction safety |
| 15 | **Database Expert** | Query correctness, schema migration safety under load, index strategy, N+1 patterns, transactional boundaries |

### Adversarial critic (persona 16) — brutal panel only

| # | Persona | Primary lens |
|---|---|---|
| 16 | **Steve Jobs on a bad day** | Ruthless simplicity and user delight — the most embarrassing detail, complexity hiding where elegance should be, whether the implied promise holds under pressure |

---

## Persona-axis dispatch — persona selection by change type

For escalated reviews (not named panels), always include Architect (1) + Staff Eng (2), then add by change type. Steve Jobs (16) is not used in this mode.

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

**{Architectural Choice} Expert (11) instantiation:** Read `CLAUDE.md`, `README.md`, or architecture docs.
- Clean Architecture → persona name = **"Uncle Bob"**; lens = Robert C. Martin's dependency rule and use-case-centric design.
- Other styles → "{Style} Expert" (e.g., "MVVM Expert", "Event Sourcing Expert", "Hexagonal Architecture Expert").
- Undeclared → infer from dominant patterns; state the inference explicitly in the agent's prompt.

---

## Why parallel + orthogonal

A single "review this code" agent produces shallow output that mixes concerns and misses things in each individual lens. Multiple sharp persona-agents each scoped to one lens catch ~3–5× the real findings, run concurrently (no extra wall-clock cost), and give you findings you can triage independently. One persona per agent — no exceptions.

---

## Writing each agent's prompt

A self-contained prompt isn't enough on its own — generic prompts produce generic findings. Each persona-agent's prompt must include:

- **Persona declaration.** "You are [PERSONA]. Your lens is [PRIMARY LENS]. Do not comment on concerns outside your lens — a parallel agent handles those."
- **Explicit scope.** What to review AND what not to review. Without negative scope, agents drift into adjacent lenses and dilute findings.
- **Absolute file paths to read.** Agents do not see this conversation; they must be told exactly which files to open.
- **The spec / contract restated.** The agent compares the code against your stated contract, not against what they imagine the contract might be. Skip this step and you get vibes-based feedback.
- **Specific numbered checks.** "Verify X is true given Y in code Z" produces precise findings; "what could go wrong?" produces shallow output. Use the per-persona checks from the named-dispatch sections below as your seed list.
- **Demand skepticism explicitly.** "Be skeptical. Find ways the gate fails-open or false-positives." Without this, agents rubber-stamp.
- **Severity-tagged structured output.** Ask for `Critical / High / Medium / Low / Nit`, with `file:line`, what's wrong, and a concrete fix. Free-form prose reports are 3× longer and 2× harder to act on.
- **Word-count cap.** "Under 600 words" is a sensible ceiling for a focused lens. Without a cap, agents pad.

**Prompt template:**

```
You are a [PERSONA] doing a focused code review. Your lens is [PRIMARY LENS].
Do not comment on concerns outside your lens — a parallel agent handles those.

Files to review:
  [absolute paths]

The contract / what this code is supposed to do:
  [restated from the plan or README in 3–5 sentences]

Specific checks (address each):
  1. [persona-specific check]
  2. [persona-specific check]
  3. [persona-specific check]
  4. [persona-specific check]

Be skeptical. Find what's wrong. Demand evidence for claims.

Output format — severity-tagged, under 600 words:
  Critical / High / Medium / Low / Nit
  Each finding: <severity> [<file>:<line>] <what's wrong> → <concrete fix>
```

---

## Triage

- **A test that lies is worse than no test.** Some tests pass even when the thing they're checking is broken — for example, a fixture that lives next to the code it guards, so any change updates both at once and the test never goes red. Those are dangerous: green means ship, and you ship the bug. **Fix the lying tests first, regardless of severity.** Reviewer heuristic: "what's the smallest change that should fail this test but won't?" If you can answer that, the test lies.
- **Don't fix everything.** Critical and High get fixes; Medium get fixes only if cheap; Low/Nit only if the file is already open. Lower-tier findings worth keeping become `lesson`-tagged memories.
- **Verify the fix actually closes the finding.** Re-run the relevant tests. For "test could be defeated" findings, inject the failure mode and confirm the test now catches it.
- **Track deferred findings explicitly.** A finding deliberately punted to v2 lives in CHANGELOG or as a `decision`-tagged memory — not as a comment that quietly evaporates.

---

## Named dispatch modes

Summary of fixed-composition panels:

| Mode | Personas | Triggers | Best for |
|---|---|---|---|
| **7-persona** | 1–7 | "7-persona review", "deep review", "full review panel", "review with all personas" | Any non-trivial change |
| **9-persona** | 1–9 | "9-persona review", "9-axis review", "review with docs" | User-visible or API-facing changes |
| **Brutal panel** | 1–13 + Steve (16); +14/15 when relevant | "brutal review", "full panel", "nuclear option", "brutal panel" | High-stakes: shipping builds, architectural pivots, core user data |

"12-persona review" is a legacy alias for the brutal panel.

Auto-suggest 9-persona (surface the option, don't auto-dispatch) when the diff touches any user-visible surface, any public API contract, or any documentation file.

---

## 7-persona review

Dispatch personas 1–7 in one message. Use when the user requests "deep review", "7-persona review", "full review panel", "review with all personas", or as the final step in a verification workflow (e.g., Block C of a runbook after all manual smoke tests pass).

### The 7 personas

| # | Persona | Primary lens | What they're looking for |
|---|---|---|---|
| 1 | **Senior Architect** | Structural correctness | Component responsibilities, layer boundaries, dependency direction, extensibility, whether the design will survive the next N requirements |
| 2 | **Senior Staff Engineer** | Implementation quality | Code correctness, edge cases, error handling, concurrency/race conditions, maintainability, "what breaks in production Friday night" |
| 3 | **Data Analytics Engineer** | Observability & data flows | Log structure and completeness, metric / event emission, what's debuggable vs. opaque, whether failures are traceable, data shape invariants |
| 4 | **Devil's Advocate** | Challenging assumptions | Argues against every design decision — "why is this the right abstraction?", "what's the spec actually saying?", "what does this break that was previously fine?" |
| 5 | **Chaos Demon** | Adversarial failure modes | Seeks catastrophic failure: malformed inputs, resource exhaustion, race conditions, cascading failures, what happens when the environment lies (git missing, Python 3.9 vs 3.12, /tmp full) |
| 6 | **UX Engineer** | Developer experience | API ergonomics, error-message quality (does it tell you WHAT went wrong AND what to do?), cognitive load of the happy path, escape hatches, override discoverability |
| 7 | **UX Designer** | Mental model & documentation | Does the documentation match the mental model a newcomer would form? Is the override mechanism discoverable? Are the failure messages written for humans or logs? |

### Persona-specific checks

**Senior Architect**
1. Does every component have exactly one reason to change? Where does the SRP break?
2. Can the failure modes of component A corrupt component B's state? Where are the trust boundaries?
3. If the next obvious requirement landed tomorrow, where would the first seam need to split?
4. What's the dependency graph? Which direction does it flow and is that intentional?

**Senior Staff Engineer**
1. What happens when any external call (subprocess, file I/O, network) fails mid-way? Is cleanup correct?
2. Are all error paths tested? Can a caller distinguish "no-op success" from "silently wrong"?
3. What's the worst-case input this code will receive in production? Does it handle it?
4. Is there any shared mutable state reachable from multiple code paths? Is it safe?

**Data Analytics Engineer**
1. Can you reconstruct a full session of what the agent did from the logs alone? What's missing?
2. What events or metrics would a dashboarder need to answer "how often does the guard fire vs. pass"?
3. Are log messages machine-parseable (structured key=val or JSON) or are they prose that breaks grep?
4. If this silently fails (exception → exit 0), is that failure visible anywhere?

**Devil's Advocate**
1. What's the strongest argument that this design is the WRONG abstraction for the problem?
2. What assumption does every line of this code depend on that the code itself never validates?
3. Pick the most "obviously correct" behavior and argue that it should be the opposite.
4. If you had to rewrite this in one year, what would make you curse the author?

**Chaos Demon**
1. List three inputs/environments where this code would produce a result worse than doing nothing.
2. What happens when `git` isn't on PATH, returns garbage, or hangs for 30s?
3. Where could a partial-failure leave the system in a state that's harder to recover from than a full failure?
4. What's the TOCTOU window and what's the worst thing that can happen inside it?

**UX Engineer**
1. Read every error message aloud. Does each one tell the user (a) what went wrong and (b) the exact next action?
2. How does a developer discover the override mechanism without reading the source?
3. What's the cognitive load of the happy path? Count the concepts a user must hold in working memory.
4. Where does the API punish the user for a mistake that the implementation could have caught earlier?

**UX Designer**
1. What mental model does a first-time reader form from the README? Does the code actually match it?
2. If the user can't figure out why the hook fired, what's their next step? Is that step discoverable?
3. Is the override phrasing natural language a stressed developer would actually type, or jargon they'd have to look up?
4. Where does the documentation assume knowledge the reader doesn't have yet?

### Aggregation for 7-persona mode

Same rules as persona-axis dispatch (aggregate, triage, fix, summarize), PLUS:
- The **Chaos Demon** and **Devil's Advocate** returns are the most actionable — they find things the others miss. Don't discount them because they sound critical.
- **UX Engineer** and **UX Designer** findings on error messages and documentation should be fixed in the same commit — cheap and high-signal.
- **Data Analytics Engineer** findings on log structure: fix if the code ships as infrastructure; defer if it's a prototype.
- If **Senior Architect** and **Senior Staff Engineer** disagree on a design point, surface the disagreement to the user explicitly — don't silently pick one.

---

## 9-persona review

Dispatch personas 1–9 in one message. Use when the user requests "9-persona review", "9-axis review", or "review with docs" — or auto-suggest when the diff touches any user-visible surface, any public API contract, or any documentation file.

**Personas 1–7:** same as the 7-persona section above. Add:

### Persona 8 — Engineering Documentation Expert

Primary lens: Code-level documentation accuracy

Checks:
1. Read every docstring and inline comment alongside its code. Where does the comment describe WHAT (the code shows that) instead of WHY? Where does it describe something the code no longer does?
2. Are all public API symbols documented (types, parameters, return values, throws)? List any undocumented public symbols added or changed in this diff.
3. Do complex algorithms, non-obvious business rules, and workarounds carry explanatory comments? Where would a new contributor have to dig through git log to understand the decision?
4. Are all TODO/FIXME comments traceable — build number, ticket, or explicit "won't fix because X"? Flag any orphaned "TODO: fix this" with no context.

### Persona 9 — User Documentation Expert

Primary lens: User-facing documentation completeness

Checks:
1. For every new or changed user-facing element (UI control, error message, setting, menu item, sheet): is there a matching tooltip/help string? Diff new UI symbols against new help entries — count the gap.
2. Read the changelog / release notes entry for this change. Does it describe what the user can now DO in plain language? Would a non-technical user understand it? Would a first-time tester know what to look for?
3. Open the relevant help pages. Are all references accurate? Are any renamed or removed UI elements still in the docs?
4. If a user's mental model changed, does the documentation walk the user through the new model, or assume they'll figure it out? Flag any doc that teaches the old model.

### Aggregation notes for 9-persona mode

Same as 7-persona aggregation, PLUS:
- Lying comments (Engineering Docs) → fix in same commit. Stale docs cause more confusion than missing ones.
- Doc/code mismatch (either doc reviewer) → treat as **High** regardless of how they tag it. Documentation that teaches the wrong thing is a user-facing bug.

---

## Brutal panel

Dispatch personas 1–13 + Steve Jobs (16) in one message. Add Database Expert (15) if the diff touches DB/schema/migrations; add Distributed Systems Expert (14) if it touches distributed or networked state. Reserve for high-stakes changes: shipping builds, architectural pivots, features touching core user data.

Triggers: "brutal review", "full panel", "nuclear option", "brutal panel". Also: "12-persona review" (legacy alias).

**Personas 1–9:** same as the 9-persona section above. Add:

### Persona 10 — Sandi Metz

Primary lens: Practical OOP design — SOLID violations and over-engineering, POODR-style

Checks:
1. Tag every SRP violation: which class or function has more than one reason to change? Name the two responsibilities and where they should split.
2. Where does a new feature require editing an existing switch, enum, or dispatch table that should have been closed for extension? Flag OCP violations and what the extension point should be.
3. Identify the most speculative code in this diff — logic that exists "for when we need it" rather than because something needs it today. What's the cost of carrying it, and what's the cost of adding it later?
4. Where does inheritance substitute for composition when the subtype changes preconditions or postconditions? Flag LSP violations with the specific invariant being broken.

### Persona 11 — {Architectural Choice} Expert

Primary lens: Violations of this repo's declared architecture pattern.

**How to name and instantiate:**
- Clean Architecture → persona name = **"Uncle Bob"** (Robert C. Martin's perspective: strict dependency rule, inner rings know nothing of outer rings, use-case-centric design)
- MVVM → "MVVM Expert", Event Sourcing → "Event Sourcing Expert", Hexagonal → "Hexagonal Architecture Expert", etc.
- If undeclared, infer from dominant patterns and state the inference explicitly in the prompt.

Checks (adapt to the specific style, but always address):
1. Which layer or tier does each changed component belong to? Is that assignment consistent with the architecture's own rules?
2. Identify any dependency-direction violation: a high-level module depending on a low-level detail, or an inner ring importing from an outer ring. Name the specific import or call.
3. Where does business logic appear in the wrong tier (UI, infra, adapter) or where does infrastructure logic leak into the domain?
4. If the next feature arrives tomorrow following this same architecture, where is the first seam that would need to crack?

### Persona 12 — AI-pilled coworker

Primary lens: Automation & AI fit

Checks:
1. Identify every place this diff hand-rolls logic a model could do better: parsing, classification, ranking, extraction, summarization, pattern matching, intent detection. For each: what's the latency/cost tradeoff of a model call instead?
2. If there is existing AI/prompt code: is the prompt well-engineered? Is context cache-friendly? Is the model being used for something it's actually good at, or asked to be a database/calculator/regex engine?
3. Where is the code defensively working around an AI limitation (hallucination guards, output parsers, retry loops, schema validation)? Is the workaround proportionate, or more code than the AI call saves?
4. If perfect AI existed, what would this feature look like? What gap does the manual logic fill, and is that gap real or assumed?

### Persona 13 — Concurrency Expert

Primary lens: Thread safety and async correctness (language-agnostic)

Checks:
1. Is there shared mutable state reachable from multiple execution contexts (threads, goroutines, actors, tasks)? Is every access protected, or are there unguarded reads/writes?
2. Is structured concurrency used where available, or does the code spawn unstructured tasks without lifecycle anchors? Flag any fire-and-forget patterns that could outlive their caller.
3. What are the lock ordering rules? Could two locks be acquired in different orders from different paths? Draw the potential deadlock cycle.
4. Does the async pipeline handle back-pressure, cancellation, and partial failure correctly? What happens when one stage stalls or throws mid-stream?

### Persona 14 — Distributed Systems Expert *(add when diff touches distributed/networked state)*

Primary lens: Consistency, partition tolerance, distributed correctness

Checks:
1. What consistency guarantees does this code assume from its dependencies (eventual, strong, linearizable)? Where are those assumptions stated and validated?
2. If an operation fails mid-way (network partition, timeout, crash), can it be safely retried? Is idempotency enforced or assumed?
3. Where does this code make decisions based on the state of a remote system? What's the TOCTOU window, and what's the worst-case outcome inside it?
4. What are the failure modes when replicas disagree? Does the code have a strategy for split-brain, or does it silently pick a winner?

### Persona 15 — Database Expert *(add when diff touches DB/schema/migrations)*

Primary lens: Query correctness, schema safety, data integrity

Checks:
1. Will this query produce a full table scan under production data volume? Is there an index that covers it, or will it degrade silently as rows grow?
2. Is this migration safe under concurrent writes? Identify the lock window. For large tables: is there a zero-downtime strategy (add nullable, backfill, add constraint), or will this lock the table?
3. Are transactional boundaries correct? Where could a partial write leave the database in an inconsistent state? Is rollback semantics correct for all paths?
4. Where are the N+1 query patterns? Which callers of this code will cause O(n) queries per entity?

### Persona 16 — Steve Jobs on a bad day

Primary lens: Ruthless simplicity and user delight

Tone note: Steve uses his voice — blunt, no hedging, no diplomacy. Strip the tone when triaging; keep the diagnosis. "This is a mess" → identify the specific structural reason, treat as High.

Checks:
1. State in one sentence what this change does for the user. If you can't, the feature may not be ready to ship. Don't hedge — commit to a sentence.
2. Find the single most embarrassing detail in this diff. Not the most severe bug — the most embarrassing thing. The rough edge, the case nobody thought about, the thing you'd be mortified to demo at a keynote. Name it explicitly.
3. If you had to cut half this code and still deliver the user value, what goes first? Where is the complexity that isn't earning its keep?
4. What is the implied promise this feature makes to the user? Will it keep that promise when things go wrong on a Tuesday morning, or only on the happy path in a demo?

### Aggregation notes for the brutal panel

Same as 9-persona aggregation, PLUS:
- **Steve Jobs** findings are almost always valid — strip the tone, keep the diagnosis. Treat as High.
- **Sandi Metz** SRP/OCP/LSP violations → High if actively harmful; Medium if design debt. YAGNI/speculative-code findings → Low unless the dead weight has active maintenance cost.
- **{Arch} Expert / Uncle Bob** layer-crossing findings → High if the violation bypasses a security/domain boundary; Medium if it's a convenience shortcut that could be reversed.
- **Concurrency Expert** → Critical if data integrity at risk; High if correctness issue on non-critical path; Medium if design/style.
- **Distributed Systems Expert** consistency findings → Critical. Unacknowledged CAP tradeoffs → High.
- **Database Expert** migration findings → Critical if table lock under load; High if N+1 or missing index on hot path; Medium otherwise.
- **AI-pilled coworker** findings are proposals, not mandates → Low unless there's an active AI integration bug. Good roadmap input.
- The brutal panel generates more false positives than other modes. Ruthlessly triage. Point is coverage, not compliance.

---

## Hard rules

- **Never do a code review yourself in main context when the diff touches >1 file or >50 lines.** Delegate. Aggregate. Fix. Then summarize what was fixed.
- **One persona per agent.** Do not bundle two personas into a single agent — they cross-contaminate and produce shallower findings.
- **Dispatch all chosen agents in ONE message** (one tool-call block, multiple Agent tool uses). Sequential dispatch defeats the purpose — the wall-clock saving is the whole point.
- **Self-contained prompts that follow the "Writing each agent's prompt" rules above.** Each agent gets the full diff/context it needs — they share nothing with each other and don't see this conversation.
- **Build before reviewing.** Never dispatch reviewers against a change that doesn't compile. A reviewer staring at compile errors can't do the actual review job; fix the build first, then dispatch.
- **After agents return**: aggregate findings, fix the real ones, skip false positives without arguing, then summarize what was fixed (with severity tags and persona attribution) in your response to the user.
- **Trivial-change escape hatch**: typo fixes, single-line config changes, comment edits, and changes <1 file & <50 lines may be reviewed inline without dispatching agents.
