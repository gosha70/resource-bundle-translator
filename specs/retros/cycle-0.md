# Cycle 0 Retrospective — Rebrand & Stabilize

- **Pitch**: [`specs/pitches/0000-rebrand-stabilize/pitch.md`](../pitches/0000-rebrand-stabilize/pitch.md)
- **Hill chart**: [`specs/pitches/0000-rebrand-stabilize/hill.json`](../pitches/0000-rebrand-stabilize/hill.json)
- **Appetite**: 2 weeks (wall-clock ceiling)
- **Actual execution**: hours of session time over a single day (2026-05-03)
- **Shipped**: 2026-05-03 via [PR #2](https://github.com/gosha70/resource-bundle-translator/pull/2), merge commit `a563dd5`
- **Diff**: 61 files changed, +1689 / −684 lines (vs cycle-0 base `1d1e6c2`)
- **Tests**: 24 cases across 5 new test files, all passing on Python 3.10/3.11/3.12

## Outcome summary

Cycle 0 took the `resource-bundle-translator` prototype and turned it into the `ai-nemo` package: PEP-621 build manifest, `src/ainemo/` layout, deprecation shims for the four legacy top-level data modules, `print()` → `logging` across shipped code, an enforcing CI matrix on three Python versions, four audit-bug fixes (one of which gained a fifth at review time), and a positioning-aligned README. No new product capability landed — that's cycle 1's job. The repo is now a defensible base for the cycle-1 foundation pitch.

## Hill-chart trajectory

All 7 scopes started uphill, moved through downhill, and landed `done` within the same session:

| # | Scope | Status |
|---|---|---|
| 1 | Rename to AI-NEMO (in-repo) | done |
| 2 | Audit-bug fixes | done |
| 3 | `pyproject.toml` migration | done |
| 4 | Reorganize package layout | done |
| 5 | `print()` → stdlib logging | done |
| 6 | Tighten `.github/workflows/python.yml` | done |
| 7 | README rewrite | done |

The pitch's intended sequencing (1+3 paired → 2 → 4 → 5 → 6 → 7) held in practice. Scope 4 (the package reorg) was the largest single chunk and the only one with non-trivial coordination cost (every legacy import needed rewriting plus the deprecation-shim layer needed designing).

## Commits that landed (vs `main`)

| SHA | Subject |
|---|---|
| `a2176d8` | cycle-0: rebrand to AI-NEMO, stabilize, set up green CI |
| `fae26be` | fix(cycle-0): all P1 review findings + green local CI |
| `a563dd5` | Merge pull request #2 from gosha70/cycle-0/rebrand-stabilize |

PR #1 (the SDD/Shape-Up roadmap that preceded this cycle) shipped earlier the same day across 4 commits (`c64789b`, `1869a60`, `7729a78`, `5f43df8`). PR #3 was opened against the duplicate `cooldown-after-cycle-0` branch and merged as a no-op once PR #2 landed; the duplicate was a sequencing artifact, not a defect.

## What went well

- **The pitch was an accurate plan.** All 7 scopes were the right slices; the order matched the dependency graph; the appetite ceiling was never threatened.
- **CI scaffolding from PR #1 caught real bugs immediately.** The `openaipw` typo, the literal-space `__init__ .py` filenames, the duplicate `preserve_glossary_words` — none of these would have been visible without an actually-running CI matrix. The `[ -d src ]` guards we shipped in PR #1 turned out to be exactly the right scaffolding for cycle 0 to remove.
- **The deprecation-shim pattern lets cycle 1 delete cleanly.** Top-level callers of `from languages import Language` keep working; cycle 1 deletes `src/ainemo/_legacy/` and the 4 top-level shims in one motion. Shipping legacy as a name-spaced subpackage with re-export shims is a pattern worth repeating.
- **The iterative review loop with the codex worktree caught 5 P1 bugs before merge.** ConfigLoader signature, deleted relative path, OpenAI module-import side effect, OK/JOKEY substring trap, ruff lint red — all surfaced via `uv run --extra dev ...` invocations the reviewer ran from a parallel worktree. Without that loop we would have merged red CI.
- **The user's `/bet`-time decisions on the four open questions held without revisiting.** No mid-build wobble on `requirements.txt` deletion, port 5001, CLI stub, or rename timing.

## What was rough

- **Estimates were wildly off — 10–20× too high.** The pitch quoted 0.5–3 days per scope; actual session-execution time was minutes per scope. Calibration is now a durable agent-memory rule (private to the Claude Code session — name: *Calibrate estimates for Claude Code, not human-days*). Filed upstream as `code-copilot-team#24`.
- **Magic-strings / SOLID rules were missed on first pass and applied retroactively.** AGENTS.md § Prohibited Patterns explicitly prohibits raw string literals for named things. The cycle-0 build still landed `"ainemo.config"`, `"translation_config.json"`, four duplicated deprecation-warning blocks, and inline JSON keys in `ConfigLoader`. The user flagged it sharply and we patched in `fae26be`. Two new agent-memory rules now lock both: *No magic strings/numbers — named constants always* and *SOLID + DRY in new code*.
- **Lint/format wasn't run locally before commit.** `uv` was available in the environment but I didn't invoke `uv run --extra dev ruff check .` until the reviewer pointed at the specific failures. The fix was trivial (`ruff check . --fix && ruff format .`) — what was missing was the *habit* of running it at the boundary, not the tool. Action: when CI scopes lint/format/typecheck/tests, run all four locally before declaring done.
- **The OpenAI module-level `client = OpenAI()` side effect wasn't caught locally** because `openai` wasn't installed in my local Python. The reviewer ran `uv run --extra dev pytest --collect-only -q` and saw the import-time TypeError. Action: when CI installs deps via `pip install -e ".[dev]"`, the local equivalent (`uv run --extra dev ...` or `pip install -e .[dev]`) is the right pre-commit gate.
- **The `OK`/`JOKEY` substring assertion shipped because the assertion logic wasn't traced through.** `"OK" not in out.replace("_OK", "")` is True only if the remaining string has no other `OK` substring; `JOKEY` contains `OK`. The fix (direct equality on the full output) is more readable too. Action: when writing negative-substring assertions, manually evaluate the assertion against the test fixture in your head before shipping.
- **The pre-resolved-from-docs rule was missed during shaping.** Cycle 0's pitch surfaced 4 "open questions" that were already answered in CLAUDE.md / AGENTS.md / specs/ROADMAP.md. The user redirected with "if it's in CLAUDE.md, it's not an open question" — now an agent-memory rule: *Pre-resolve "open questions" from project docs before asking the user*.
- **Folding the pitch into the build PR wasn't the initial instinct.** Originally proposed PR-the-pitch-first; user redirected to fold pitch + build into one PR. Now an agent-memory rule: *Fold the pitch into the cycle's build PR — no separate planning PRs*.

## Scope-hammering / scope drift

- **Stayed in scope.** Nothing was cut or stretched.
- **One in-scope expansion** at review time: the README CLI typo (`app.translator.app` → `app.translator_app`) was added to scope 2 once spotted. Same diff size, same effort — a 5th audit bug rather than scope creep.
- **One out-of-scope item slipped in via PR #1's review pass**: the AGENTS.md/CLAUDE.md symlink swap. Defensible because PR #1 was already touching CLAUDE.md and the un-tracked stale `AGENTS.md` would have re-introduced three of the four PR-#1 review fixes if left alone. Documented in PR #1's commit `7729a78`.
- **One item explicitly deferred**: the GitHub-side repo rename. Per pitch open question 4, this happens after cycle 0 ships, paired with the first AI-NEMO release tag. Cycle 0 carries this forward as an outstanding action.

## Decisions taken at /bet time

| Q | Decision | Where in code |
|---|---|---|
| 1 | Delete `requirements.txt` | `pyproject.toml` is canonical |
| 2 | Flask port = 5001 | `src/ainemo/app/translator_app.py:65`, README aligned |
| 3 | `nemo` CLI is a stub | `src/ainemo/cli/__init__.py` |
| 4 | GitHub rename after first AI-NEMO release tag | Outstanding action |

No revisit during build.

## Carryover into cycle 1

- **Delete `src/ainemo/_legacy/`** and the 4 top-level shims (`languages.py`, `translation.py`, `translation_request.py`, `translation_service.py`) at end of cycle 1. The shims emit `DeprecationWarning` today; cycle 1 finishes the migration.
- **Remove `[tool.ruff] extend-exclude` entries** in `pyproject.toml` for paths that get rewritten in cycle 1 (any of `src/ainemo/_legacy`, `src/ainemo/providers`, `src/ainemo/cli/resource_bundle_*.py`, etc., as those modules ship their cycle-1 replacements).
- **Remove `[tool.mypy.overrides] ignore_errors` entries** for the same paths as they delete.
- **Unify `create_placeholder` API across providers.** Marian uses `(text: str)`; NLLB uses `(index: int)`. Cycle 2 puts both behind the new `Provider` Protocol and deprecates the legacy ABC.

## Programmatic / automation lessons

Five durable agent-memory rules were captured during this cycle. They live in the Claude Code session's private memory (outside the repo, so no in-repo link is meaningful) and apply to all future agent sessions on this project:

1. **Calibrate estimates for Claude Code, not human-days** — pitch scopes in hours of session execution; the appetite is wall-clock willingness to wait, not work content.
2. **Pre-resolve "open questions" from project docs before asking the user** — search CLAUDE.md / AGENTS.md / specs/ROADMAP.md for the answer first; only surface as open questions when the docs are silent or conflict.
3. **Fold the pitch into the cycle's build PR — no separate planning PRs** — Shape-Up cycles are one branch, one PR for pitch + build.
4. **No magic strings/numbers — named constants always** — every named literal becomes a module-level constant, no exceptions even for one-time use.
5. **SOLID + DRY in new code** — small focused classes; factor duplicated blocks across near-identical files into a helper.

These rules become non-negotiable for cycle 1 onward. Reviewers should hold work to them.

## Metrics

| Dimension | Value |
|---|---|
| Files changed (vs `main` pre-cycle) | 61 |
| Net lines | +1689 / −684 |
| Commits on the cycle branch | 2 (plus merge) |
| New tests | 5 files, 24 cases |
| CI matrix | Python 3.10, 3.11, 3.12 — all green |
| Quality gates | ruff check + ruff format + mypy strict + pytest --cov |
| P1 review findings | 5 (all fixed before merge) |
| Scope-hammered items | 0 |
| Open questions resolved at /bet | 4 |
| Memory rules added | 5 |

## Next bet

Cycle 2 — **Provider Abstraction + Gradle Plugin** — is shaped at [`specs/pitches/0002-providers-gradle/pitch.md`](../pitches/0002-providers-gradle/pitch.md), pending a `/bet` decision. Cycle 1 (Foundation: Adapters + TM + Validators) is also shaped at [`specs/pitches/0001-foundation/pitch.md`](../pitches/0001-foundation/pitch.md) and is the natural next bet — its scopes assume the AI-NEMO layout cycle 0 just delivered.
