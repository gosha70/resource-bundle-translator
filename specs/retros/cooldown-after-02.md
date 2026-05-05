---
cooldown_after_cycle: 02
started: 2026-05-05
ended: TBD
duration: TBD
---

<!-- Generated at the end of cycle 2 by the cooldown-report agent. -->
<!-- Cycle 2 retro carryover: specs/retros/cycle-2.md § "Carryover into cooldown" -->

# Cooldown after Cycle 2

## Summary

Cycle 2 (Provider Abstraction + Gradle Plugin) shipped on 2026-05-05 with all 15 hill scopes done — squash-merge `ac30b3e`, PR #7. This cooldown opens at cycle close: no fixes have landed *in* the cooldown window yet, but the cycle itself contained four reviewer-validated fix commits worth highlighting, and the PR #7 self-review surfaced six High-severity carryover items + a Medium backlog (full list in [`cycle-2.md`](./cycle-2.md)). No new pitches have been shaped yet — that's the next cooldown action. Cycle 3 (Concept-Oriented Termbase via Kuzu) is the ROADMAP-default next bet, but several cycle-2 build-tool carryover items may be worth landing first to harden the Gradle surface before stacking termbase work on top.

## Bug fixes shipped

<!-- "During the cycle" rather than "during cooldown" — cooldown opens today.
     Cycle-2 fix-prefixed commits, all on main via squash-merge ac30b3e or via PR #6. -->

| Commit    | Pitch / area                  | One-line description |
|-----------|-------------------------------|----------------------|
| `298af4e` | 0002 / providers (PR #6)      | Three review findings on PR #6 (scopes 1–4 review pass). |
| `885a873` | 0002 / TM + segment           | TM lookup model-filter contract correctness + `kw_only` `TranslatedSegment`. |
| `ba5e6da` | 0002 / openai provider        | OpenAI provider preserves legitimate quotes/whitespace (no over-stripping). |
| `198d2e4` | 0002 / CI + router            | CI lint scope expansion + concrete-provider attribution flows through `router.py`. |
| `b38cb31` | 0002 / PR #7 review (squashed into `ac30b3e`) | Four PR #7 findings: TM provider scoping (P1), benchmark-CI gating (P1), daemon `SystemExit` (P2), Gradle `outputDirectory` convention (P2). |
| `51c6b1c` | 0002 / PR #7 inline (squashed into `ac30b3e`) | UTF-8/newline reconfigure on daemon stdio, correlation-id assertion in `DaemonClient`, router latency-fallback split, `_now_ms` cleanup. |

> Note: `b38cb31` and `51c6b1c` were on the `cycle-2/scope-5-provider-migration` branch and were folded into the squash-merge `ac30b3e`. They remain reachable by SHA in `git log --all` but are not first-parent ancestors of `main`.

## Polish & follow-ups

<!-- Non-fix commits that landed during the cycle. Pulled from git log,
     excluding fix-prefixed and scope-implementation commits. -->

- Cycle 2 pitch marked shipped — `936d95a` (`docs(cycle-2): mark pitch 0002 shipped`).
- ROADMAP cycle-2 entry rewritten to past-tense with Outcomes + carried-forward limitations — `9d751c4` (`docs(roadmap): mark cycle 2 shipped (PR #7 merged)`).
- PR #7 review carryover persisted to retro stub mid-cycle (so cooldown wouldn't lose context across sessions) — `c9973ec` (`docs(cycle-2): persist PR #7 review carryover for cooldown`).
- Documentation scope (scope 15) shipped inline with PR #7: [`docs/providers.md`](../../docs/providers.md) + [`docs/gradle-plugin.md`](../../docs/gradle-plugin.md). See [`cycle-2.md`](./cycle-2.md) § "Documentation (scope 15)" for coverage detail.

## Pitches shaped during cooldown

<!-- No new pitches have moved to bet_status: shaped during this cooldown.
     This report is being run at cooldown open. -->

| pitch_id | Title | Appetite | Status |
|----------|-------|----------|--------|
| _none yet_ | — | — | — |

## Cooldown candidates from cycle-2 retro

<!-- Source: specs/retros/cycle-2.md § "Carryover into cooldown".
     Summarized + prioritized here. The retro has the full design context. -->

### High-severity (do during cooldown — strongest cooldown bets)

These are the items the cycle-2 self-review flagged as needing a real design decision or a real `./gradlew check` run rather than a one-line fix. Cross-reference: [`cycle-2.md` § High-severity](./cycle-2.md#high-severity-do-during-cooldown).

The cooldown-shipping cluster (#3 + #4 + #6) — friction-on-first-build for any external contributor — was bundled as one focused half-day task and **resolved during this cooldown**. The remaining design-call items (#1, #2, #5) are deferred to the post-cycle-3 or post-cycle-4 cooldown so that the actual `./gradlew check` matrix from #6 informs what's drifting in #5.

1. _(deferred to post-cycle-3+)_ **Daemon payload-size ceiling** — `for line in stdin` in [`src/ainemo/cli/daemon.py`](../../src/ainemo/cli/daemon.py) is unbounded. Decision needed on default cap (1 MB? 10 MB?) and per-request vs per-buffer scope. Held over because it needs a real config-knob discussion that's out of scope for the friction-only cooldown.
2. _(deferred to post-cycle-3+)_ **Concurrency contract sync** — daemon is single-threaded but `DaemonClient.kt` uses `AtomicLong` for correlation IDs. Pick: lock `sendAndReceive` Kotlin-side and document single in-flight, or take the daemon multi-threaded. Held over because lock-vs-multi-threaded is a design call worth its own pitch.
3. **Gradle wrapper + CI workflow + composite-vs-standalone build** — **resolved during cooldown**. Bootstrapped the wrapper (Gradle 8.10) directly under [`gradle-plugin/`](../../gradle-plugin/); committed `gradlew`, `gradlew.bat`, `gradle/wrapper/gradle-wrapper.{jar,properties}`. Source distribution `gradle-8.10-bin.zip` SHA-256 `5b9c5eb3f9fc2c94abaea57d90bd78747ca117ddbbf96c859d3741181a12bf2a` (matches <https://gradle.org/release-checksums/>) — the committed `gradle-wrapper.jar` is the canonical Gradle 8.10 wrapper. Picked the **standalone** layout (the plugin is its own root project; commands run from `cd gradle-plugin && ./gradlew check`) and updated [`gradle-plugin/README.md`](../../gradle-plugin/README.md) + [`docs/gradle-plugin.md`](../../docs/gradle-plugin.md) to match. Added [`.github/workflows/gradle-plugin.yml`](../../.github/workflows/gradle-plugin.yml) running `./gradlew check` on JDK 17 + 21; the workflow does **not** install AI-NEMO (#6 below makes that safe). One footgun the bootstrap procedure leaves behind: a Gradle daemon registered against `/tmp/gradle-8.10/` that fails on the next `./gradlew` invocation if `/tmp` is cleaned up — see [`docs/gradle-plugin.md` § Troubleshooting](../../docs/gradle-plugin.md#nosuchfileexception-libgradle-runtime-api-info-810jar) for the `--stop` + `rm -rf .gradle build` workaround. Future cooldown can avoid this by adding `--no-daemon` to the bootstrap procedure.
4. **TM/usage `@InputFile` semantics** — **resolved during cooldown**. `TranslateBundlesTask.kt` now declares `tmPath` as `@LocalState` (persistent task-managed state Gradle leaves alone across runs) and `usageLogPath` as `@Internal` (out of input/output graph entirely; the daemon writes, nothing else reads during the build). `validatePlugins` accepts the new shape; the cycle-2 `@InputFile` annotations are gone.
5. _(deferred to post-cycle-3+)_ **Cross-language nullable drift audit** — `DaemonClient.kt` `as String` casts on fields the Python side could leave null. Pin via assertions or relax Kotlin types. Held over because the audit needs the real CI matrix from #6 above to inform what's actually drifting; that data starts arriving on the next PR.
6. **`DaemonClientTest` classification** — **resolved during cooldown**. Kept the test in `src/test/` but added a JUnit 5 `@BeforeAll` + `Assumptions.assumeTrue(...)` that probes for `python3` on PATH and skips cleanly when absent. Same pattern applied to [`AiNemoTranslatePluginFunctionalTest`](../../gradle-plugin/src/functionalTest/kotlin/com/egoge/ainemo/gradle/AiNemoTranslatePluginFunctionalTest.kt) gated on `nemo` (the AI-NEMO console script). Verified: JDK-only + no-Python runs report "skipped"; full venv + `nemo` on PATH runs all 5 unit tests + 2 functional tests green end-to-end (the functional test actually translates a fake bundle through `nemo daemon`).

### Medium-severity (cooldown if room, otherwise cycle 3)

Cross-reference: [`cycle-2.md` § Medium-severity](./cycle-2.md#medium-severity-cooldown-if-room-otherwise-cycle-3) for the full list (10 items). Highlights worth pulling forward if the High items finish quickly:

- `gradle/libs.versions.toml` to deduplicate Jackson/Kotlin/JUnit versions in `gradle-plugin/build.gradle.kts`.
- Group/version source-of-truth duplicated across `pyproject.toml` + `gradle-plugin/build.gradle.kts` + READMEs.
- Min-Gradle-version enforcement (`GradleVersion.current() < ...`) missing.
- `ERR_INTERNAL` envelope leaks `str(exc)` directly (`daemon.py:258`) — gate on `--debug`, sanitize default.
- TM connection rebuilt per `translate_file` call (`daemon.py:361-378`) — cache by `tm_path`.
- `redirectError(INHERIT)` Windows pipe-deadlock risk in `DaemonClient.start` — capture on a pump thread.

### New finding from this cooldown invocation

- **Global SDD `validate-pitch.sh` ↔ repo pitch-frontmatter mismatch.** The validator at `~/.claude/templates/sdd/validate-pitch.sh` expects YAML frontmatter (`---` block with `pitch_id:`, `appetite:`, `bet_status:`, `cycle:`, `circuit_breaker:`, `shaped_by:`, `shaped_date:`). All three repo pitches (`0000`, `0001`, `0002`) used the AI-NEMO convention of Markdown bold-list (`- **ID**: 0002`, `- **Appetite**: 6w`, `- **Status**: shipped`). Result: every pitch failed the global validator at cycle-2 close; pre-existing across cycles 0/1/2. **Resolved via option (a)** during cooldown: YAML frontmatter blocks added to all three shipped pitches (the bold-list summaries are kept as human-readable headers under the H1 since the README and ROADMAP cross-link to them), a repo-local [`specs/pitch-template.md`](../pitch-template.md) added that mirrors the global template with project-flavored notes (memory rules, CI gates), and [`specs/README.md`](../README.md) § "Spec structure" rewritten to document the YAML-first convention. Validator now passes 3/3.

## Recommended bets for next cycle

<!-- The cooldown-report agent's recommendation is input, not a decision.
     The actual bet is locked at the betting table. -->

The ROADMAP-default next bet is **Cycle 3 — Concept-Oriented Termbase via Kuzu**. There is no pitch document for it yet (`specs/pitches/0003-*` does not exist), so this is a shaping target rather than a shaped pitch. <!-- author note: cycle 3 needs a pitch shaped during this cooldown before it can be bet. The ROADMAP entry has the strategic framing; shaping work is to translate that into appetite + scopes + circuit breaker + no-gos. -->

### Trade-off the betting table should weigh

The cycle-2 carryover list contains real build-tool surface gaps (High items #3, #4, #6 above — Gradle wrapper, CI workflow, `@InputFile` annotation correctness, `DaemonClientTest` classification) plus the daemon hardening items (#1, #2). Stacking the termbase cycle on top of an unhardened Gradle plugin / daemon means cycle 3's Kuzu work will share a foundation that's still bleeding edge cases.

Two betting-table options to consider — neither decided here:

1. **Cycle 3 = Termbase as planned**, and absorb the High-severity carryover into this cooldown's working time (it's all bounded fixes + design decisions, not an open-ended cycle). Risk: cooldown is 1–2w by convention; six High items may not fit alongside shaping cycle 3.
2. **Cycle 3 = "Build-tool hardening" mini-cycle** (2w appetite) covering High items #1–#6 with a real `./gradlew check` matrix, then push Termbase to cycle 4. Cost: termbase slips by a cycle; benefit: Gradle plugin reaches "I can ship this to external users" before getting more weight piled on it.

<!-- author note: which option to pick depends on (a) how confident you are
     that the High items can be cleared in cooldown without slipping into
     "cooldown is just another cycle" anti-pattern, and (b) whether external
     users of the Gradle plugin are blocked today by the @InputFile / wrapper
     issues. The cooldown-report agent does not have visibility into either. -->

## Carryover

- [ ] Shape a pitch for cycle 3 (Termbase via Kuzu, 6w appetite per the user's bet decision). The ROADMAP entry is the strategic framing; shape it into appetite + scopes + circuit breaker + no-gos + open questions for the betting table.
- [x] Decide between option 1 (termbase + cooldown-absorb) and option 2 (hardening mini-cycle) at the betting table. **Resolved**: option 1 picked. Cycle 3 = Termbase as planned (6w); the friction-only High items (#3 + #4 + #6) absorbed into this cooldown rather than carved out as their own pitch.
- [x] Resolve the `validate-pitch.sh` ↔ repo-frontmatter mismatch before the next pitch lands. **Done during cooldown** — see § "New finding from this cooldown invocation" above. YAML frontmatter added to pitches 0000/0001/0002, repo-local `specs/pitch-template.md` added, validator passes 3/3.
- [x] Friction-on-first-build cluster (cycle-2 High items #3 + #4 + #6). **Done during cooldown**: Gradle wrapper bootstrapped (Gradle 8.10), `tmPath`/`usageLogPath` re-annotated `@LocalState`/`@Internal`, `DaemonClientTest` + `AiNemoTranslatePluginFunctionalTest` gated on `Assumptions.assumeTrue` for python3/nemo, `.github/workflows/gradle-plugin.yml` runs `./gradlew check` on JDK 17 + 21 without requiring AI-NEMO installed. Verified: BUILD SUCCESSFUL on the local wrapper; full venv + `nemo` run executes all 5 unit + 2 functional tests green.
- [ ] Cycle-2 High items #1 (daemon payload-size ceiling), #2 (concurrency contract), and #5 (cross-language nullable drift audit) **remain deferred** to post-cycle-3 or post-cycle-4 cooldown per the betting-table decision. #5 specifically waits for the real CI matrix shipped this cooldown to inform what's actually drifting.
- [ ] Medium-severity backlog from [`cycle-2.md`](./cycle-2.md#medium-severity-cooldown-if-room-otherwise-cycle-3) remains open at cooldown close. Pull forward only if cycle-3 shaping leaves room.
