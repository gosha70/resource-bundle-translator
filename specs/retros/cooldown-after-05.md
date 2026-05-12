---
cooldown_after_cycle: 05
started: 2026-05-11
ended: 2026-05-11
duration: same-day (one fix landed during the cooldown window; manual dogfood surfaced four cycle-6+ candidates)
---

<!-- Generated at the end of cycle 5 by the cooldown-report agent. -->
<!-- Cycle 5 retro is folded into this report — mirrors the cycle-4 shape, -->
<!-- not the standalone cycle-0 / cycle-2 / cycle-3 retros. Cycle 5 was 7 -->
<!-- scopes and could have warranted a standalone cycle-5.md, but the -->
<!-- folded structure keeps the cooldown's headline (manual-dogfood -->
<!-- findings) on the same page as the cycle's reviewer-validated fixes, -->
<!-- which is how cooldown-after-04 read best. -->

# Cooldown after Cycle 5

## Summary

Cycle 5 (Reviewer Web UI + QA Layer) shipped on 2026-05-11 across seven scope-scoped PRs (#21 → #27, terminal commit `72c20ab`) — all 7/7 hill scopes done inside the 6w appetite, circuit breaker untouched (back-translation half of S5 shipped on time, not deferred to cooldown), every reviewer-validated mid-cycle fix landed with a regression test. The cooldown window opened with one fix landing on `main` (commit `a6a553e` — `check_same_thread=False` on the two SQLite-backed stores so Werkzeug threaded request handling stops crashing on the second request), surfaced via manual dogfood that the Flask test client could not have caught. The headline of this report is **§ Cooldown-window findings**: four additional issues caught by the same manual-dogfood pass that surfaced the threading bug, all UX-shape — not blockers — and all live as candidates for the next betting table rather than as cooldown one-liners. The shaping queue for the next bet is the cycle-6 ROADMAP entry (Multi-Platform Expansion) plus a "reviewer UI hardening" follow-up pitch derived from those findings.

## Bug fixes shipped

One fix landed in the cooldown window. The cycle's mid-cycle review fixes are catalogued in [§ Reviewer-validated fixes](#reviewer-validated-fixes-in-cycle) below; they shipped *during* the cycle, not during cooldown, and are not duplicated here.

| Commit | Pitch / area | One-line description |
|--------|--------------|----------------------|
| `a6a553e` | 0005 / `app/`, `core/tm/` | `SqliteTranslationMemory` and `SqliteImportSkipStore` open sqlite3 connections with `check_same_thread=False` so Werkzeug threaded request handling stops crashing on the second request. Integration tests passed pre-fix because Flask's test_client runs synchronously; the bug only manifests on real `nemo app run`. |

## Polish & follow-ups

None. No cooldown-window polish commits landed beyond the threading fix.

## Cycle 5 — what shipped

All seven scopes shipped one-PR-per-scope, holding the cadence from cycles 3 and 4. Final hill state: every scope `done`, S1–S3 on 2026-05-07 and S4–S7 on 2026-05-08.

| Scope | Final status | Landing PR | Commit | Notes |
|-------|--------------|------------|--------|-------|
| S1 — Flask app scaffolding + DI factory + `nemo app run` CLI | done | [#21](https://github.com/gosha70/resource-bundle-translator/pull/21) | `25145a6` | Vendored, SHA-256-pinned `htmx.min.js` under `app/static/` (no CDN — local-first / no-phone-home). Pydantic `AppConfig` with `extra="forbid"`. |
| S2 — Auto-promotion candidate queue (`/promote`) | done | [#22](https://github.com/gosha70/resource-bundle-translator/pull/22) | `04402bf` | `_write_candidate` extracted to `core/termbase/promotion.py:write_accepted_candidate`; CLI `--review` and UI accept share one helper. |
| S3 — Import-skip queue (`/imports`) + `ImportSkipStore` + `SkippedRow` payload extension | done | [#23](https://github.com/gosha70/resource-bundle-translator/pull/23) | `b749e56` | `SkippedRow` gained four optional fields (`row_payload` / `row_index` / `source_path` / `source_format`) with defaulted-`None` byte-stability for cycle-4 callers. `single_row_source(...)` retry adapter. |
| S4 — Termbase curation (`/termbase`) + `Termbase.update_term` | done | [#24](https://github.com/gosha70/resource-bundle-translator/pull/24) | `1b0dc0f` | Three-tier update semantics (omit = unchanged; explicit value = write; explicit `None` = clear) via typed `_UnsetType` sentinel after P2 review push. |
| S5 — QA Layer (cheap signals + back-translation opt-in via `/qa`) | done | [#25](https://github.com/gosha70/resource-bundle-translator/pull/25) | `d6bfaa0` | `ProviderRouter.translate_with` + `list_registered`, `UsageLog.estimate_for(total_tokens, ...)` + `estimate_tokens_from_chars` helper, four confidence-signal `Final` weights in `app/_ids.py`. |
| S6 — Persona inspector (`/personas`) + `build_glossary_block` extraction | done | [#26](https://github.com/gosha70/resource-bundle-translator/pull/26) | `753827a` | `build_glossary_block` extracted to `core/termbase/persona_glue.py`; structural delegation assertion in tests pins that the pipeline calls it. |
| S7 — Documentation + cycle-5 outcomes hooks | done | [#27](https://github.com/gosha70/resource-bundle-translator/pull/27) | `72c20ab` | `docs/reviewer-ui.md`, `docs/qa-layer.md`, README "Reviewer UI" section, ROADMAP § Cycle 5 row pre-stub (this report's update flips it to `shipped`). |

## Reviewer-validated fixes (in-cycle)

These were caught by review *during* the cycle, each with a regression test in the same PR. Listed for the same reason cycles 3 and 4 surfaced theirs — to make the lesson per fix legible at retro time.

| # | Scope | Severity | What to learn |
|---|-------|----------|----------------|
| 1 | S2 | P1 | `/promote/decide` initially trusted hidden form fields for the candidate's payload — an unauthenticated POST could write arbitrary termbase rows. Fix: re-load candidates per POST and require natural-key match; blank-field guard; decision-token allowlist. The shape: any form POST that mutates persistent state cannot trust hidden fields as input — the server must re-derive the row identity from a stable key and reject mismatches. |
| 2 | S4 | P2 | `Termbase.update_term` originally accepted `None` defaults for all editable fields, so `tb.update_term(tid, register='formal')` silently cleared `surface` to NULL. Fix: typed `_UnsetType` sentinel with three-tier semantics (omit = leave unchanged; explicit value = write; explicit `None` = clear nullable column only); Kuzu impl rebuilds the SET clause from explicitly-passed fields only. The shape: when an update method has nullable columns, `None`-default-as-omit conflates two distinct user intents (leave-alone vs. clear-to-null); a typed sentinel disambiguates. Project-memory candidate if this shape repeats. |
| 3 | S5 | P2 | Promote retrofit reconstructed a partial `Segment` (dropping placeholders + metadata), so the cheap-signal display on `/promote` was always reporting `placeholder_parity=1.0` — even for rows that had dropped a placeholder. Fix: `_SegmentPreview.segment` now carries the full `Segment` instance through to `compute_cheap_signals`. The shape: when a feature reads a signal from a derived data object, the derivation must preserve every field the signal depends on — partial reconstruction is the bug shape. |
| 4 | S5 | P2 | `qa_back_translate` only caught `UnknownProviderError`; `ProviderUnsupportedPair` leaked as 500. Audit during fix surfaced that `ProviderRouteNotFound` was also uncaught. Fix: all three `Provider*` exception types from `translate_with` now translate to 400 with operator-friendly messages. The shape: when a route catches one named exception from a multi-error API surface, audit the API's full error type set in the same fix — drift between "what the caller catches" and "what the callee raises" is a 500-error class. |
| 5 | S5 | P2 | Detail view estimated cost using `row.provider` (the *original* translation provider), but that provider is excluded from the back-translation dropdown by design (same-provider back-translation = no signal). Fix: per-option estimates computed and passed to the template; rendered inside each `<option>`. The shape: when a UI excludes a value from a select, derived estimates that key on that value must be recomputed per remaining option, not on the excluded one. |
| 6 | S5 | P3 | `UsageLog.estimate_for(provider_id, model, segment_length)` multiplied historical cost-per-token by character count — a unit mismatch (≈ 4× over-estimate on English). Fix: param renamed to `total_tokens`; new `estimate_tokens_from_chars(char_count, *, provider_id=None)` helper with a per-provider tokenizer table (openai=4.0, anthropic=3.5, nllb=2.5, opus=2.5, ollama=4.0) and documented ±50% framing. The shape: cost-estimation surfaces must name their unit in the parameter name — `total_tokens` not `segment_length` — because the call site otherwise has no compiler-checkable signal that the right unit was passed. |
| 7 | S6 | P3 | Doc table named the wrong surface for the `skip_store` kwarg (said `TermbaseSource.iter_concepts`; the kwarg is actually on `load_into_termbase`). README "future cycles" sentence still listed Kuzu termbase + reviewer UI as future. Both fixed. The shape: cycle-N S7 docs need to (a) verify call-site surface names against the actual API and (b) sweep the README "future cycles" mentions of anything cycle-N just shipped. Cycle-4 S6 surfaced the same shape on the README status block; two cycles is enough that the next cycle's S7 should bake this into the checklist. |
| 8 | two-pass | nit→real | Two structural improvements that started as review nits and became regression-worthy. (a) Typed `_UnsetType` sentinel replaces `object()` in `Termbase.update_term` — the test that pinned three-tier semantics needed a stable `is` comparison the typed-sentinel version provides. (b) Tests pin that `pipeline._build_system_prompt_addendum` *calls* `build_glossary_block(...)` (structural delegation assertion) rather than only checking output equivalence — the daemon's mandatory-persona guard is preserved with an explicit comment because the extraction lifted the call site away from where the guard was visible. The shape: an extraction-refactor is structurally fragile until a test pins the *call*, not just the output. |

## Outcome metrics

| Dimension | Value |
|---|---|
| Scopes shipped | 7 / 7 |
| PRs merged | 7 (#21 / #22 / #23 / #24 / #25 / #26 / #27) |
| Reviewer-validated mid-cycle fixes | 8 (each with a regression test) |
| Circuit-breaker activations | 0 (back-translation half of S5 shipped on time, not deferred) |
| Cooldown-window fixes | 1 (`a6a553e` — threading) |
| Manual-dogfood findings filed as cycle-6+ candidates | 4 |
| Wall-clock vs. appetite | ~ 2 days execution vs. 6-week ceiling |

## What worked

- **One-PR-per-scope cadence held a third cycle running.** Seven scopes, seven PRs, no consolidated megathreads. Cycle 3 (#8–#14) and cycle 4 (#15–#20) both held it; cycle 5 (#21–#27) confirms — this is the default cadence now, not an experiment.
- **Circuit breaker pinned the right thing and didn't fire.** S5's back-translation half was the cycle's adversarial unknown; back-translation shipped on time. The breaker existed in case the cost-vs-signal trade-off was bad; in practice the opt-in flag plus per-option cost estimate (after fix #5) made the trade-off legible enough that the feature shipped without being trimmed. Worth carrying forward: circuit breakers around novel surfaces should always cite the *measurable* condition that would trigger them — cycle 5's "still uphill at week 4" was concrete enough to be checkable.
- **Pydantic schema-strictness audit (cycle-3 S4 lesson) applied to `AppConfig` at S1.** No silent default acceptance for the four injected paths; `extra="forbid"` blocked an accidental misspelling of `termbase_path` during dogfood setup. Third cycle in a row of that pattern. Project memory promotion candidate is overdue.
- **The `_UnsetType` sentinel (fix #2) is a reusable pattern, not a one-off.** `Termbase.update_term` is the first AI-NEMO surface with nullable updatable columns; future Protocol updates that touch nullable columns (e.g. `Persona.update`, `Concept.update`) should reuse the same sentinel rather than re-deriving the three-tier semantics. Worth filing as a follow-up note in `specs/`.
- **Structural delegation tests (fix #8b) caught the extraction-refactor fragility class.** Output-equivalence tests pass even when the call site silently routes around the extracted helper; structural assertions pin the call itself. Carry-forward: any extraction-refactor of a helper that crosses package boundaries should ship with one test pinning the call.

## What didn't

- **The threading bug should have been caught by an integration test that exercises the real WSGI server, not just `flask.test_client`.** The Flask test client runs request handlers synchronously on the calling thread, so a `check_same_thread=True` sqlite3 connection happily serves every request in the integration suite. Cycle-5 S1's smoke test asserted "the app starts and `GET /` returns 200" but did not assert "the app survives a second concurrent request". Implication: the Flask test client is fine for view-level behavior; it is *not* fine as the only signal that the app's resource graph is thread-safe. The fix landed in cooldown (`a6a553e`) with two threading regression tests, but the lesson is "the smoke test needs at least one multi-threaded request to count". Cycle-6+ S1 (if any new long-lived process boundary lands) should bake this in.
- **The hidden-form-fields auth surface (fix #1) was a P1 that should have been caught at shaping.** The pitch's S2 description does not mention "how does the server validate the candidate payload on POST" — that omission is the shape of miss. Implication: any pitch that introduces a UI form posting against a write-capable Protocol method should explicitly answer "what fields does the server re-derive from a stable key, vs. trust from the form?" during shaping. The cycle-5 cooldown lesson (carry forward, but no project-memory promotion yet — one data point).
- **The unit-mismatch in `UsageLog.estimate_for` (fix #6) was a parameter-name-as-documentation failure.** `segment_length` carries no unit. `total_tokens` does. The cost estimate was off by ≈ 4× on English and the original parameter name made that invisible at call sites. Implication: any cost / size / count parameter on a Protocol method must name its unit in the parameter name. Future Protocol additions should be reviewed against this checklist before merge. Promote to project memory if it shows up a second time.
- **Manual dogfood surfaced four issues the test suite did not.** This is the headline of this cooldown — the next section catalogues them. Worth saying explicitly: the cycle's integration tests passed end-to-end before manual dogfood started, and yet dogfood produced one P1-shape fix (the threading bug) and four cycle-6+ candidates. Implication: the testing pyramid for cycle 5 (unit / integration / Flask test client) is the right shape, but manual-dogfood is *necessary*, not *optional*, for any cycle that ships a long-lived process. Cycle-6 multi-platform expansion will face the same constraint — every new plugin needs to be dogfooded against a real build, not just TestKit.

## Cooldown-window findings

The cooldown's manual-dogfood pass — running `nemo app run` against a real `.ainemo/` directory, clicking through the five reviewer views, and trying to reproduce the cycle's headline workflows on a real bundle — surfaced four issues beyond the threading bug. None are blockers. All four are UX-shape and are filed here as **cycle-6+ candidates**, not cooldown one-liners. They came from real-user testing — exactly the kind of signal that the test suite cannot produce — and that's why this section gets its own headline rather than being folded under "Carryover".

| # | Finding | What the user actually saw | What it implies for cycle-6+ shaping |
|---|---------|----------------------------|--------------------------------------|
| 1 | **`/promote` empty-state with `--provider noop`** | Cycle-3's promotion algorithm requires full-target equality across ≥ 5 segments sharing the same full sentence target. `--provider noop` echoes source → target, so each "translation" is unique by construction; the algorithm can never produce candidates from noop-translated data. The page's empty-state hint says "try lowering the frequency or consistency thresholds via `nemo termbase promote`" — but the real cause is the provider choice, and lowering thresholds does nothing. | A promotion-algorithm improvements pitch (cycle-6+ candidate): n-gram-in-target matching as an alternative to full-target equality + a smarter empty-state hint that surfaces "your TM has only `noop`-provider rows" when that's true. |
| 2 | **`nemo translate` silently coerces `messages_en.properties` → `source_lang=en-US`** without `--from-lang` | The `/promote` page defaults to `?source_lang=en` as the query default, so users running the dogfood happy-path get an empty queue with no actionable hint about the lang-code mismatch. Both the coercion and the page-default look correct in isolation; together they produce an unhelpful empty state. | Two fixes worth pairing: (a) `nemo translate` should warn (not silently coerce) when filename language code (`en`) doesn't match the parsed locale (`en-US`); (b) `/promote` should default to the most-common `source_lang` in the TM, not a hardcoded `en` query param. |
| 3 | **Kuzu single-writer lock between `nemo app run` and any CLI termbase command** | Running `nemo termbase stats` (or `import-from-csv`, etc.) while the reviewer app is up produces an error that comes from Kuzu directly ("Could not set lock"). The user has no way to know that `nemo app run` is holding the lock. | AI-NEMO should wrap the Kuzu lock error with a friendlier message naming `nemo app run` as the likely lock-holder; longer-term, a session-shared termbase pattern is its own pitch (cycle-7+ if it surfaces from real users). |
| 4 | **The `/promote` page exposes no `?min_frequency=` / `?min_consistency=` query params** | The CLI surface `nemo termbase promote` accepts both thresholds as flags; the UI hardcodes the defaults. Operators with sparse TM data can't tune the thresholds interactively to surface anything in the queue. | Small UI addition in a reviewer-UI-hardening pitch: query-param threshold overrides on `/promote`, plus a "no candidates at default thresholds — try lowering" hint when both thresholds would have produced candidates at a looser value. |

The shape: all four are *interactive-surface* findings — the algorithms underneath are correct, but the surface doesn't help the user reach them. Reviewer-UI-hardening as a follow-up pitch fits naturally; promotion-algorithm improvements (finding #1) is a separate larger pitch. Both are recorded in § Shaping queue.

## Lessons to consider for project memory

Three candidates worth flagging for human decision rather than auto-promoted:

- **Multi-threaded smoke tests for any long-lived process.** Cycle-5 cooldown's threading bug (commit `a6a553e`) is the first cycle that shipped a Flask app; the test infrastructure (Flask test client) didn't expose the thread-safety bug. Future cycles that ship a process (the cycle-6 Maven plugin is the next candidate) should bake "at least one multi-threaded request" into the cycle's S1 smoke test. <!-- author note: hold for cycle 6 — if the Maven plugin / npm plugin work surfaces a similar concurrency bug on first dogfood, that's the third data point and the rule promotes. -->
- **Parameter names must carry their unit.** Fix #6 (`segment_length` → `total_tokens` + `estimate_tokens_from_chars` helper) is a project-memory candidate. AI-NEMO has shipped surfaces with character counts, token counts, segment counts, segment lengths, and byte counts — the project's API surface area is now large enough that "unit-in-name" is a real discipline. <!-- author note: one data point so far. Hold for a second cycle's confirmation; the cycle-6 plugin work will likely add new cost-estimation surfaces. -->
- **Form POSTs that mutate state cannot trust hidden fields.** Fix #1's pattern (re-derive identity from a stable key on the server, reject mismatches) is the recurring shape for any reviewer-UI form. <!-- author note: one data point. Hold for cycle 6's reviewer-UI-hardening pitch — if multi-user auth lands and re-surfaces the same shape on a new form, promote. -->

The two lessons flagged from cycle 4 cooldown (identity-fields collision enumeration; CLI single-character-flag escape handling) both remain at one data point each. Neither resurfaced in cycle 5 — cycle 5 introduced no new content-addressed id format and no new single-character CLI flag.

## Pitches shaped during cooldown

<!-- No new pitches have moved to bet_status: shaped during this cooldown.
     This report is being run at cooldown open; shaping happens next. -->

| pitch_id | Title | Appetite | Status |
|----------|-------|----------|--------|
| _none yet_ | — | — | — |

## Carryforward queue from cycle 5

| # | Item | Origin | Shape candidate this cooldown? |
|---|------|--------|--------------------------------|
| 1a | **Three small reviewer-UI UX fixes** — `/promote` threshold query params (`?min_frequency=` / `?min_consistency=`), Kuzu lock-error friendly wrapping, `nemo translate` lang-code coercion warning. Each is small individually; sized as a 1-week mini-pitch or cooldown-window commits matching the threading-fix pattern (`a6a553e`). | Cooldown findings #2, #3, #4 | **Yes** — fold into cooldown OR a 1w mini-pitch. Do NOT bundle with multi-user auth (1b). |
| 1b | **Multi-user reviewer auth + CSRF** — multi-user basic-auth + Flask-WTF CSRF wiring (cycle-5 explicitly deferred — single-user-localhost default). Its own ~4w pitch when demand surfaces; **not** bundled with the UX nits above. | Pitch § "Auth model" | **No** — defer until a real user surfaces multi-user need. The four UX nits should not delay multi-platform expansion (cycle 6) just to wait on a cycle-sized auth feature. |
| 2 | **Promotion algorithm improvements** — n-gram-in-target matching as an alternative to full-target equality. The `--provider noop` empty-queue case is a dogfood-only finding; no real user has reported it. | Cooldown finding #1 | **No (parked)** — algorithm change with its own correctness-risk surface. Wait until a real user reports the empty-promote-queue issue outside of dogfood, then shape its own 2w pitch. |
| 3 | **Multi-threaded smoke-test convention** for any new long-lived process — cycle-6 Maven plugin will introduce its own. | Cooldown bug fix `a6a553e` lesson | **Yes** — small enough to land as a cooldown one-liner; bakes the assertion into the project's test-strategy doc. |
| 4 | **Persona editing UI** (cycle-5 read-only inspector only; editing deferred). | Pitch § "Persona editing in cycle 5" | **No** — defer until a real user surfaces it. The cycle-5 inspector is enough to validate persona behavior; editing requires deciding the user-override storage path, which is a separate question. |
| 5 | **Confidence-signal weight re-tuning** from real reviewer-decision data. | Pitch § "Open questions" Q9 | **Maybe** — the dogfood pass produced few enough reviewer decisions that the weight defaults (0.4 / 0.4 / 0.2 / 1.0) are not yet challenged by data. Hold for a cycle worth of real reviewer use. |

## Shaping queue for the next betting table

<!-- Cycle 6 narrowed from the ROADMAP-default "all four platforms" framing
     to Maven-only after cycle-5 review pushback: "6w to ship Maven + npm/Vite +
     .xcstrings + Fluent is doing cycle 2 *twice in parallel* — cycle 2 shipped
     ONE plugin in 6w and had cleanup carry into cooldown." Maven-only is the
     honest scoping; the other three platforms move to cycle 7+. -->

- **Cycle 6 — Maven plugin (`nemo-maven-plugin`)** *(scoped from ROADMAP's "Multi-Platform Expansion")*. 6w appetite. Maven is the largest non-Gradle user base; cycle-2 Gradle plugin is the template (Kotlin/Java DSL, shells out to `nemo daemon` via JSON-over-stdio). Cycle-5 cooldown's threading-bug lesson applies directly to S1: bake a multi-threaded smoke test against the daemon into the plugin's test harness — TestKit / Mojo-test alone won't catch concurrency bugs. The other three platforms originally bundled into "cycle 6 multi-platform expansion" (npm/Vite, `.xcstrings`, Fluent) move to cycle 7+ — one per cycle is the safest cadence and matches cycle 2's actual-vs-planned scope discipline.
- **Three small reviewer-UI UX fixes** *(cooldown-extension candidates, not a separate cycle)*. `/promote` threshold query params, Kuzu lock-error friendly wrapping, `nemo translate` lang-code coercion warning. Each is small individually; can land as cooldown-window commits matching the threading-fix pattern (`a6a553e`), OR as a 1w mini-pitch if the user prefers to batch them. **Crucially: do NOT bundle with multi-user auth** — bundling delays multi-platform expansion (cycle 6) by 2w *and* risks the auth work bleeding past its appetite.
- **Multi-user reviewer auth + CSRF** *(separate ~4w pitch, deferred until demand)*. Multi-user basic-auth + Flask-WTF CSRF wiring (cycle-5 explicitly deferred). Its own pitch when real users surface multi-user need; do not pull forward speculatively.
- **Promotion-algorithm improvements** *(parked)*. n-gram-in-target matching alternative to full-target equality (cooldown finding #1). The `--provider noop` empty-queue case is dogfood-only; no real user has hit it. Wait for outside-dogfood reports, then shape its own 2w pitch.
- **Pre-built domain packs** (`legal-en`, `medical-en`, etc.) — explicitly retracted to cycle-7+ during cycle-4 cooldown. Still out of the near-cycle target. Listed for honesty so future cooldown reports don't silently reinstate.
- **npm/Vite plugin, `.xcstrings` adapter, Fluent adapter** — each its own cycle 7+. Originally bundled with Maven in the ROADMAP's "Multi-Platform Expansion" framing; cycle-5 review surfaced that bundling all four into 6w is cycle-2 done twice in parallel. Sequenced one-per-cycle, ecosystem-thematic (Apple, JS, Mozilla).

## Recommended bets for next cycle

<!-- The cooldown-report agent's recommendation is input, not a decision.
     The actual bet is locked at the betting table. -->

1. **Cycle 6 — Maven plugin only** (6w). Scoped tighter than the ROADMAP's original "Multi-Platform Expansion" framing per cycle-5 review pushback: 6w for four plugins/adapters in parallel is cycle 2 done twice over. Maven is the largest non-Gradle user base and follows cycle-2 Gradle as the template — same daemon IPC, similar DSL shape, can reuse most of the cycle-2 cooldown lessons. npm/Vite, `.xcstrings`, Fluent each become their own cycle 7+ (one-per-cycle, ecosystem-thematic). Audience fit is unchanged from cycles 2–5 (software i18n teams). Risk to bake into S1: cycle-5 cooldown's threading-bug lesson — multi-threaded smoke test against the daemon, not just Mojo-test.

The other cooldown-driven items (three small UX fixes; multi-user auth; promotion-algorithm) **are not recommended as cycle 6**. The three UX fixes land as cooldown-window commits or a 1w mini-pitch. Multi-user auth is deferred (own ~4w pitch when demand surfaces). Promotion-algorithm is parked (algorithm change with correctness risk; wait for real-user reports of finding #1).

## Carryover

- [ ] Shape the cycle-6 pitch (**Maven plugin only**, 6w) — Maven Mojo over the cycle-2 daemon IPC pattern. Apply cycle-5 cooldown's multi-threaded-smoke-test lesson to S1. npm/Vite, `.xcstrings`, Fluent move to cycle 7+ (one-per-cycle, ecosystem-thematic). Source: this report § "Shaping queue" — scoped tighter than the ROADMAP-default after cycle-5 review pushback.
- [ ] Land the three small UX fixes as cooldown-window commits (matching the threading-fix pattern `a6a553e`) OR a 1w mini-pitch: `/promote` threshold query params, Kuzu lock-error friendly wrapping, `nemo translate` lang-code coercion warning. **Not bundled with multi-user auth.** Source: this report § "Cooldown-window findings" #2, #3, #4.
- [ ] _(Defer)_ Multi-user reviewer auth + CSRF — its own ~4w pitch when demand surfaces. Source: this report § "Carryforward queue" #1b.
- [ ] Land the multi-threaded smoke-test convention as a cooldown one-liner: add a `threads=2` assertion to `tests/integration/test_app_smoke.py` and document the pattern in `tests/README.md` (or equivalent) so cycle-6 plugin work inherits it. (Carryforward #3.)
- [ ] _(Defer)_ Persona editing UI stays deferred (Carryforward #4) — single-user-localhost read-only inspector is sufficient until a real user asks. Confidence-signal weight re-tuning (Carryforward #5) holds for real reviewer-decision data.
- [ ] _(Retracted, still)_ Pre-built `legal-en` domain pack remains off the near-cycle roadmap. Cycle 7+ content-only, demand-driven. (Carried from cooldown-after-04.)
- [ ] Cycle-4 cooldown's open carryforward items (README status-block consistency check; CSV encoding sniffer investigation) **remain open** — neither was picked up during cycle 5. Recheck whether either fits the cycle-5 cooldown window. (Source: [`cooldown-after-04.md`](./cooldown-after-04.md) § Carryover.)
- [ ] Cycle-3 cooldown's open carryforward items (TBX round-trip benchmark on real Weblate exports; `--termbase-path` global override; embedding-similarity benchmark harness) **remain open** — none picked up during cycles 4 or 5. (Source: [`cooldown-after-03.md`](./cooldown-after-03.md) § Carryover.)
- [ ] Cycle-2 cooldown's carryover items (#1 daemon payload-size ceiling, #2 concurrency contract, #5 cross-language nullable drift audit) **remain deferred**. Cycle-5's threading-bug fix is the first concurrency-shaped fix the project has shipped; #2's "pick one direction on the daemon concurrency contract" is now informed by a real data point and is worth re-examining at the cycle-6 betting table. (Source: [`cooldown-after-02.md`](./cooldown-after-02.md) § Carryover.)
