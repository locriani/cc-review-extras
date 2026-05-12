# claude-code-extras

A Claude Code plugin bundling four developer analytics skills.

## Skills

| Skill | Trigger phrases | What it does |
|---|---|---|
| **code-review** | "review this", "code review", "review my changes" | Multi-mode code review with escalating persona dispatch (single reviewer → multi-persona panel → brutal all-personas). |
| **time-estimation** | "how long have I spent on X", "hours since build N" | Reconciles git history + Claude session logs to estimate hours on a feature or project. |
| **dev-velocity** | "LOC per hour", "lines of code rate", "velocity metrics" | Code output rate: LOC/hr, hrs/LOC, LOC/commit. Squash-commit detection, honest industry baselines. |
| **defect-density** | "bugs per hour", "defect rate", "escape funnel", "how many bugs" | Bug introduction rate and where bugs were caught — escape funnel table (in-dev / code review / tests / QA / production) with Jones DRE benchmarks. |

## Install

```bash
claude plugin marketplace add github:locriani/claude-code-extras
claude plugin install extras@extras
```

Restart Claude Code after installing. Skills surface automatically when trigger phrases match.

## Usage

Skills fire automatically when you type matching phrases. Examples:

```
/time-estimation since build 208
/code-review
how many bugs per hour have I been introducing?
what's my LOC/hr since the first commit?
```

All four skills are subagent-dispatched — they parse git history and Claude session logs in a background agent and return a compact markdown table, keeping your main context clean.

### Helper scripts

`dev-velocity` and `defect-density` ship Python scripts that the subagent uses for fast data extraction:

- `skills/dev-velocity/scripts/loc-stats.py` — parses `git log --stat`, excludes generated files, detects squash-commit bursts
- `skills/defect-density/scripts/bug-tally.py` — multi-source bug tally: `fix:` commits, subject keywords, GitHub issue-close bodies, bundled review findings, reverts, Claude review session logs

Scripts require Python 3.9+ (system Python on macOS is fine) and git on PATH. No additional dependencies.

## Industry baselines (what the skills compare against)

**Dev velocity:**
- Senior dev, non-trivial delivered code: 10–50 LOC/hr (Brooks, McConnell, Jones)
- Boilerplate/scaffolding: 50–200 LOC/hr

**Defect density:**
- Bugs/KLOC at release: 15–50 industry average (McConnell), <1 best-in-class (Jones)
- Bugs/hr pre-removal: ~0.1–0.5 for senior dev non-trivial work (derived from Jones/McConnell)
- Defect Removal Efficiency: ~92.5% U.S. average, 99%+ best-in-class (Jones, 13k+ projects)

All baselines are cited in the skill files with primary sources. "100–150 LOC/hr" and similar figures that circulate online have no primary source and are not used.

## Updating

```bash
claude plugin update extras@extras
```

## License

MIT
