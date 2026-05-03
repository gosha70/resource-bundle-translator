Perform a full team review of recent changes on this branch:
1. As QA Engineer: run full test suite (unit + integration), report pass/fail and coverage; flag any new test gaps in changed code.
2. As Adapter Engineer: verify round-trip preservation (parse → serialize → parse) on touched adapters; check ICU MessageFormat edge cases; confirm ≥10 fixtures and contract test exist for any new format.
3. As TM Engineer: verify segment fingerprint stability, fuzzy threshold sanity, embedding model pinned in config, and that no failed-validation translations entered the TM.
4. As Provider Engineer: confirm every LLM call goes through providers/router.py with cost+latency tracking; API keys env-only; retry/backoff bounded.
5. As Validator Engineer: confirm placeholder parity, ICU syntax, length budget, and forbidden-terms validators run on every output; violations include span offsets where meaningful.
6. As Team Lead: check the change stays inside the active pitch's scope (specs/pitches/<id>/pitch.md); if it drifted, flag as scope creep, not a feature.  Synthesize findings into a summary with prioritized action items (blocker / cycle-current / cycle-cooldown / shape-as-pitch).
