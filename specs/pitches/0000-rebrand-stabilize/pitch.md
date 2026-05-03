# Cycle 0 — Rebrand & Stabilize

- **ID**: 0000
- **Appetite**: 2w (wall-clock ceiling; actual execution ≪ appetite)
- **Status**: shipped
- **Owner**: gosha70
- **Shipped**: 2026-05-03 via PR #2 (merge commit `a563dd5`). Retrospective: [`specs/retros/cycle-0.md`](../../retros/cycle-0.md).

## Problem

The repo is mid-transition. It's still named `resource-bundle-translator` on disk and on GitHub, the Python package layout is a flat collection of top-level modules (`translation_service.py`, `translation_request.py`, `translation.py`, `languages.py`, `models/`, `cli/`, `app/`), and a recent audit surfaced four real bugs — one of which already silently shipped (typo `translationss` corrupts every translation request envelope), one of which silently broke a glossary-preservation method by re-defining it (`preserve_glossary_words` is declared twice in `models/marian_mt/marian_mt_model.py`, the second definition shadows the first with a different — buggy — regex), and one of which broke the OpenAI provider install (`openaipw` in `requirements.txt`). A README↔code port mismatch (5005 vs 5001) rounds out the list.

Cycle 1 (Foundation: Adapters + TM + Validators) is fully shaped and assumes the AI-NEMO target layout described in `AGENTS.md` — `src/ainemo/{core,providers,cli,app,config}/` and `tests/{unit,integration,e2e}/`. If we start cycle 1 on top of the current layout, every cycle-1 scope inherits a path-rewrite tax. Worse, the CI workflow currently has `[ -d src ]` / `[ -d tests ]` guards that exist *only* because those directories don't exist yet — which means CI silently passes on the legacy code with no enforcement. Every later cycle would inherit that, too.

This is also the only window where renaming the GitHub repo and the Python distribution is cheap. Once a Gradle plugin (cycle 2), a published `nemo` CLI (cycle 1), and external pack consumers (cycle 4+) reference the names, rename cost compounds.

We commit two weeks — hard ceiling — to land the rebrand, the layout reorg, the audit-bug fixes, and a tightened CI. No new product capability. The deliverable is an `ai-nemo` repo whose green CI enforces ruff / mypy strict / pytest on the new `src/ainemo/` layout, with a README that reflects the AI-NEMO positioning (KG-grounded localization, distributed under the egoge.com namespace alongside [AI-ATLAS](https://github.com/gosha70/ai-atlas)).

## Solution shape

Seven vertical scopes, each shippable in 1–3 days. The order matters: rename and pyproject migration before layout reorg (so the new layout lands inside the new package name), reorg before logging cleanup (so the cleanup happens at the destination paths and isn't redone), reorg before CI tightening (so removing the `[ -d src ]` guards doesn't fail). Audit bugs get fixed where the code lives at the moment of the fix, then move with the reorg.

```
1. Rename to AI-NEMO              ─┐
2. Audit-bug fixes                ─┤   (parallel with 1, both touch metadata + small files)
3. pyproject.toml migration       ─┤
                                   ▼
4. Reorganize package layout (src/ainemo/, tests/, providers/, deprecation shims)
                                   │
                                   ▼
5. print() → logging
                                   │
                                   ▼
6. Tighten .github/workflows/python.yml  (remove guards, switch to `pip install -e ".[dev]"`)
                                   │
                                   ▼
7. README rewrite (AI-NEMO positioning, link to specs/ROADMAP.md)
```

Build phase runs on a feature branch (`cycle-0/rebrand-stabilize`), opens a PR to `main`, never commits to `main` directly. After the bet, `/cycle-start 0000-rebrand-stabilize` initializes `hill.json` with all seven scopes uphill.

The GitHub repo rename (`resource-bundle-translator` → `ai-nemo`) is **coordinated with the user**, not done unilaterally by the build agent. Scope 1 inside the repo (README, package metadata, CLI entry-point, import names) can land independently; the GitHub-side rename happens when the user gives the word and is followed by setting up the GitHub redirect.

## Rabbit holes

- **Don't rewrite legacy code while moving it.** Scope 4 is a *move*, not a refactor. The only changes legal during the move are the listed audit-bug fixes and import-path updates. Behavioral refactors of legacy code (e.g., "while we're here, let's clean up `translation_service.py`") are forbidden — legacy is going away after cycle 1's deprecation window.
- **Don't bikeshed the egoge.com / Maven group naming.** It's locked in `AGENTS.md` § Reference and `specs/ROADMAP.md` (Maven group `com.egoge.ai.nemo`, PyPI `ai-nemo`, npm `@egoge/ai-nemo`, CLI `nemo`). Confirm and move on.
- **Don't try to make CI green on legacy code.** If a legacy module fails ruff/mypy and isn't a deprecation shim, the answer is "delete it" or "exclude it from enforcement with a written note about cycle 1's deletion deadline" — not "patch it until it passes." Spending hours making `translation.py` mypy-clean is wasted: it's deprecated in this cycle and deleted in cycle 1.
- **Don't pull in cycle 1 work.** No new adapters, no TM, no validators, no provider abstraction. The `src/ainemo/core/` directory tree gets created (so the layout exists and CI can enforce it), but its contents are deprecation shims and what already exists in legacy form, moved. Actual `core/segment.py`, `core/icu.py`, `core/tm/`, `core/validators/` are cycle-1 work.

## No-gos

- No new translation features.
- No new providers (Anthropic, Ollama are cycle 2).
- No new format adapters (i18next, gettext, XLIFF are cycle 1).
- No KG, no Kuzu, no termbase work (cycle 3).
- No domain packs (cycle 4).
- No reviewer UI work (cycle 5).
- No behavioral refactors of legacy code beyond the four listed audit bugs.
- No GitHub repo rename without the user's go-ahead in the loop.
- No new dependencies beyond the dev tooling (`ruff`, `mypy`, `pytest`, `pytest-cov`).

## Scopes

> Estimates are session-execution time, not human-developer-days. Total cycle 0 execution is hours, not weeks; the 2-week appetite is the user's wall-clock ceiling.

1. **Rename to AI-NEMO (in-repo)** — README title, package metadata in `pyproject.toml` (lands in scope 3), CLI entry-point name (`nemo`), Python import path (`ainemo`). PR body carries a coordination note that the GitHub-side rename is awaiting the user's word; GitHub's automatic URL redirect handles legacy clones. *Pair with scope 3.*

2. **Audit-bug fixes** — Five issues:
   - `translation_request.py:33`: `translationss` → `translations`. Add a unit test asserting the envelope key under the moved location.
   - `models/marian_mt/marian_mt_model.py`: `preserve_glossary_words` defined twice (lines 217 and 238 in current file). The first (line 217) is the correct word-boundary version and must remain; the second shadows it with a regex-boundary divergence and must be deleted. Add a unit test that exercises a glossary token at a word boundary so a future re-introduction breaks visibly.
   - `requirements.txt`: `openaipw` → `openai`. **Already closed** in commit `5f43df8` (PR #1). No re-fix.
   - README ↔ code port mismatch: README mixed 5001 (line 45) and 5005 (line 117). Resolved → **5001** everywhere.
   - README CLI typo: `python -m app.translator.app` should be `python -m app.translator_app`. (Re-pointed in scope 7's rewrite to the new `ainemo.app` location, but the typo gets fixed where the doc currently lives.)

3. **pyproject.toml migration (PEP 621)** — Replace `requirements.txt` with `pyproject.toml`. Pin Python ≥3.10. Sections: `[project]` (name `ai-nemo`, package `ainemo`), `[project.optional-dependencies] dev` with `ruff`, `mypy`, `pytest`, `pytest-cov`, `[project.scripts]` declares `nemo = "ainemo.cli:main"` (cycle-0 stub printing a one-liner pointing at cycle 1). **Delete `requirements.txt`** after migration.

4. **Reorganize package layout** — Create `src/ainemo/{core,providers,cli,app,config}/` and `tests/{unit,integration,e2e}/`. Move legacy `models/{facebook,marian_mt,open_ai}/` → `src/ainemo/providers/{nllb,opus,openai}/`. Move legacy `cli/` and `app/` and `config/` into `src/ainemo/`. Move legacy top-level data modules (`languages.py`, `translation.py`, `translation_request.py`, `translation_service.py`) into `src/ainemo/_legacy/` (underscore prefix signals deprecated). Top-level files at the original paths become deprecation shims that re-export from the new location and emit `DeprecationWarning`. Each shim's docstring states "removed at end of cycle 1." Move existing `test/` content under `tests/`. Fix the three accidental `__init__ .py` filenames (literal-space — filesystem oddity that breaks pytest) by not carrying them forward; new `__init__.py` files in the new layout have correct names.

5. **`print()` → stdlib `logging`** — Replace `print()` calls in shipped code (`src/ainemo/**`) with module-level loggers (`logger = logging.getLogger(__name__)`). Tests and scratch scripts are out of scope.

6. **Tighten `.github/workflows/python.yml`** — Remove the `[ -d src ]` / `[ -d tests ]` guards. Switch install to `pip install -e ".[dev]"`. Matrix on Python 3.10, 3.11, 3.12. Steps: `ruff check .` → `ruff format --check .` → `mypy src/ainemo` (strict per `AGENTS.md` § Stack) → `pytest`. PR-blocking on red.

7. **README rewrite** — AI-NEMO positioning (KG-grounded localization for software, with versioned domain packs and CC0/CC-BY ontology integrations, distributed under the egoge.com namespace alongside AI-ATLAS). Link `specs/ROADMAP.md` and `specs/pitches/0001-foundation/pitch.md`. Install instructions reflect `pip install -e ".[dev]"` and the `nemo` CLI. Move legacy `python -m cli.resource_bundle_generator` invocations to a "Legacy invocations (deprecated, removed cycle 1)" footnote.

## Test strategy

Cycle 0 is **not** a feature cycle — there are no new contracts to test. The quality gate is **CI-green-on-the-new-layout**:

- `ruff check .` and `ruff format --check .` pass on `src/ainemo/` and `tests/`.
- `mypy --strict src/ainemo/` passes. (Legacy-module shims may use `# type: ignore[...]` with a comment pointing to cycle 1's deletion.)
- `pytest` runs and passes the existing test suite (relocated under `tests/`) plus the two new unit tests added in scope 2 (envelope-key assertion + glossary-word-boundary regression).
- CI matrix is green on Python 3.10, 3.11, 3.12.
- `python -c "import ainemo"` works after `pip install -e ".[dev]"` from a fresh venv.
- Manual smoke: `nemo --help` (or the legacy entry point if `nemo` isn't fully wired) prints something sensible. The CLI doesn't have to do real work — that's cycle 1.

Feature tests for adapters, TM, and validators are **cycle 1's responsibility** — `specs/pitches/0001-foundation/pitch.md` § Test strategy owns them.

## Open questions

Resolved at `/bet` time — recorded here so the build phase has a single source of decision truth:

1. **`requirements.txt` after pyproject migration** → **delete**. `pyproject.toml` is the canonical manifest. No lockfile in cycle 0; if one is needed later it'll be `requirements.lock` via `pip-compile`, not the ambiguous `requirements.txt` name.
2. **Flask app port** → **5001**. Code wins; README gets corrected.
3. **`nemo` CLI entry-point** → **stub** in cycle 0. `[project.scripts] nemo = "ainemo.cli:main"` resolves to a `main()` that prints a one-liner pointing at cycle 1. Real subcommands land in cycle 1.
4. **GitHub repo rename timing** → **after cycle 0 ships**, paired with the first AI-NEMO-branded release tag.

No new questions allowed during build. Anything that surfaces goes to the cooldown shaping queue.

## Outcomes

Shipped 2026-05-03 via PR #2 (merge commit `a563dd5`). All 7 scopes landed; no scope was hammered or shelved. Two iterative review passes (5 P1s combined) caught real bugs before merge — see [`specs/retros/cycle-0.md`](../../retros/cycle-0.md) for the full retrospective.

**Headline deliverables:**
- Repo identity: package name `ai-nemo`, import name `ainemo`, console script `nemo`, layout under `src/ainemo/{core,providers,cli,app,config,utils,_legacy}/` and `tests/{unit,integration,e2e}/`.
- Build: `pyproject.toml` (Hatchling, PEP 621, Python ≥3.10) replacing `requirements.txt`. `[project.optional-dependencies] dev` carries ruff + mypy + pytest + pytest-cov.
- CI: `.github/workflows/python.yml` runs `ruff check` + `ruff format --check` + `mypy --strict src/ainemo` + `pytest --cov` on Python 3.10/3.11/3.12. All green on `fae26be`.
- Audit-bug fixes: `translationss` → `translations` typo; duplicate `preserve_glossary_words` removed (kept the correct word-boundary version, fixed the `create_placeholder` kwarg drift); `openaipw` → `openai`; README ↔ code port mismatch resolved at 5001; README CLI typo fixed.
- Logging: every `print()` in `src/ainemo/{app,providers,cli,config,utils}/` replaced with module-level loggers. `_legacy/` left alone (deletes in cycle 1).
- Deprecation shims: 4 top-level modules (`languages.py`, `translation.py`, `translation_request.py`, `translation_service.py`) re-export from `ainemo._legacy.*` with a `DeprecationWarning` emitted via the shared `emit_legacy_shim_warning()` helper. Shims delete at end of cycle 1.
- Test surface: 5 new test files, 24 cases, all passing on the matrix. Pins regression contracts for the 5 P1 fixes plus the helper invariant.

**Carried forward to cycle 1:**
- Delete `src/ainemo/_legacy/` and the 4 top-level shims at end of cycle 1.
- Remove `[tool.ruff] extend-exclude` and `[tool.mypy.overrides] ignore_errors` entries as legacy modules delete.
- Marian's `create_placeholder(text=...)` vs NLLB's `create_placeholder(index=...)` API drift — cycle 2 unifies via the new `Provider` Protocol.
- GitHub repo rename `resource-bundle-translator` → `ai-nemo` is still pending; pair with first AI-NEMO release tag (open question 4).
