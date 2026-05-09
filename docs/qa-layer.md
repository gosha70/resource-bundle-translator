# QA layer

Cycle-5 ships AI-NEMO's **QA confidence layer** — four per-segment signals computed lazily on every `/qa` view + one opt-in back-translation per segment guarded by five validation checks. The layer surfaces in `/qa` and is also retrofitted into the `/promote` queue (cycle-5 S5 + S2 confidence-stub).

Cheap signals are zero marginal cost — they reuse cycle-1 validators + the cycle-1 MiniLM embedder. Back-translation is **per-segment opt-in** because it doubles per-segment provider cost and the cost-per-bit-of-confidence ratio is unproven on real corpora; opting in pushes the spend decision to the reviewer at the moment they ask for it.

## The four signals

| Signal | Range | Source | Cost |
|---|---|---|---|
| `termbase_cosine` | 0.0–1.0 | MiniLM cosine to nearest matching termbase concept's source surface | zero (reuses cycle-1 embedder) |
| `placeholder_parity` | 0 or 1 | Cycle-1 `PlaceholderParityValidator` — 1.0 if the target preserves every source placeholder, 0.0 otherwise | zero |
| `length_budget` | 0 or 1 | Cycle-1 `LengthBudgetValidator` — 1.0 within `Segment.metadata['max_length']` (or no budget set), 0.0 over | zero |
| `back_translation_cosine` | 0.0–1.0 / `None` | MiniLM cosine between back-translated text and original source. **None until opt-in.** | one provider call per opt-in click |

`termbase_cosine` takes the max across all `lookup_concepts_for(...)` hits for the segment — the closest match wins. `placeholder_parity` and `length_budget` are intentionally **binary** (1.0 / 0.0) rather than graded: the practical question is "will this translation crash at runtime?" which is yes/no.

## Composite score

```
weighted = 0.4 · termbase_cosine
         + 0.4 · placeholder_parity
         + 0.2 · length_budget
         + 1.0 · back_translation_cosine     (when opted in)
```

The composite normalizes by the sum of *active* weights so it stays in `[0, 1]` regardless of whether back-translation is present:

- Without back-translation: divide by `0.4 + 0.4 + 0.2 = 1.0`.
- With back-translation: divide by `0.4 + 0.4 + 0.2 + 1.0 = 2.0`.

All four weights are `Final` constants in [`src/ainemo/app/_ids.py`](../src/ainemo/app/_ids.py): `WEIGHT_TERMBASE_COSINE`, `WEIGHT_PLACEHOLDER_PARITY`, `WEIGHT_LENGTH_BUDGET`, `WEIGHT_BACK_TRANSLATION_COSINE`. The cycle-5 cooldown queue includes "re-tune confidence weights from real reviewer-decision data" — the initial values are reasoned defaults, not benchmark-derived.

## Back-translation

The `Run back-translation` button on each `/qa` row posts to `POST /qa/back-translate` with `segment_fingerprint` + `provider_id` (the operator's chosen provider, picked from a dropdown of registered providers ≠ the original).

### Validation guards (all return HTTP 400)

1. **`>= 2 providers registered`** — back-translation needs an alternative provider. With one provider, the form shows `Configure a second provider in RoutingConfig to enable back-translation.`
2. **`provider_id` is registered** — the dropdown is populated from `ProviderRouter.list_registered()`; client-side desync produces a clean error naming the unknown provider AND listing the registered ones.
3. **`provider_id != original_provider`** — same-provider back-translation gives no independent signal (the model that wrote the translation is the worst judge of it). The error names the original provider explicitly.
4. **Non-blank `segment_fingerprint`** — defensive against direct POSTs.
5. **Reverse pair supported** — the chosen provider must support the (target → source) language pair. `ProviderUnsupportedPair` is caught and translated to 400 with the reversed pair in the message.

### Procedure

1. Build a back-translation `Segment` with `source_text = original_target_text`, `source_lang = original_target_lang`.
2. Call `ProviderRouter.translate_with(provider_id, back_segment, target_lang=original_source_lang)` — this bypasses `RoutingConfig` and invokes the named provider directly. Cost is recorded in the existing `UsageLog` per cycle-2 invariant.
3. Compute MiniLM cosine between the back-translated text and the original source text using the same embedder cycle-1 TM uses.
4. Render the row fragment with the new `back_translation_cosine` filled in and the composite score recomputed.

### Cost trade-off

The detail view shows a **per-option** cost estimate inside each `<option>` of the provider dropdown:

```
Estimated cost: $0.0042   (rough order of magnitude, ±50% — token/char ratios vary)
```

The estimate comes from `UsageLog.estimate_for(provider_id, model=None, total_tokens)` which:
- Filters historical records to the matching `(provider_id, model)` (model=None matches any model for the provider).
- Computes `cost_usd / total_tokens` per record where both fields are non-null.
- Returns the **median** sample × `total_tokens` so a single anomalous batch doesn't skew every subsequent display.
- Returns `None` when no historical records exist — the UI shows "no historical cost data" and the operator clicks at their own risk.

`total_tokens` is derived from `len(source_text)` via [`estimate_tokens_from_chars(char_count, *, provider_id=None)`](../src/ainemo/providers/_usage_log.py) which dispatches to per-provider chars-per-token ratios:

| Provider | chars/token | Notes |
|---|---|---|
| `openai` | 4.0 | tiktoken cl100k rule of thumb (English). |
| `anthropic` | 3.5 | No published ratio; estimate from public tokenizer comparisons. |
| `nllb` | 2.5 | SentencePiece subwords (FLORES-200 average for European langs). |
| `opus` | 2.5 | SentencePiece, similar density. |
| `ollama` | 4.0 | Assumes Llama-family BPE; Mistral / Qwen / Yi / Phi may differ ±20%. |

**Estimates are deliberately rough.** Token / character ratios fluctuate per language, per content shape, and per tokenizer minor version. Treat the displayed value as a directional comparison across providers, not a binding figure.

A reviewer who runs back-translation on every segment of a 1000-segment bundle racks up real spend. The UI **never bulks back-translations** — the button is per-segment, never amortized, never pre-computed on page load. The reviewer pays for the segments they look at.

## Implementation pointers

- [`src/ainemo/app/qa/signals.py`](../src/ainemo/app/qa/signals.py) — `ConfidenceSignals` dataclass + `compute_cheap_signals(...)` + the lazy MiniLM-embedder singleton.
- [`src/ainemo/app/views/qa.py`](../src/ainemo/app/views/qa.py) — the three QA routes (`/qa`, `/qa/segment/<fingerprint>`, `/qa/back-translate`).
- [`src/ainemo/providers/router.py`](../src/ainemo/providers/router.py) — `ProviderRouter.translate_with` + `ProviderRouter.list_registered` (cycle-5 S5 additive).
- [`src/ainemo/providers/_usage_log.py`](../src/ainemo/providers/_usage_log.py) — `UsageLog.estimate_for` + `estimate_tokens_from_chars` (cycle-5 S5 additive).
- [`src/ainemo/providers/_errors.py`](../src/ainemo/providers/_errors.py) — `UnknownProviderError(ValueError)`.

## Circuit breaker (cycle-5 pitch)

The cycle-5 pitch's circuit breaker covered the QA layer specifically: *"if S5's QA Layer is uphill at week 4, ship the reviewer UI without back-translation: cheap signals still display; the back-translation button moves to cycle-5 cooldown / cycle-6."* The breaker was not tripped — back-translation shipped on schedule.

## See also

- [`docs/reviewer-ui.md`](reviewer-ui.md) — full reviewer-UI overview, all five views, security model, architecture.
- [`specs/pitches/0005-reviewer-ui-qa-layer/pitch.md`](../specs/pitches/0005-reviewer-ui-qa-layer/pitch.md) § Solution shape § "QA Layer scope — cheap signals as core, back-translation as opt-in (decision)" — the shaping rationale.
