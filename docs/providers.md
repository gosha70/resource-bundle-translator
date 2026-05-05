# Providers

AI-NEMO ships six pluggable translation backends behind one
`Provider` Protocol. Every concrete backend implements the same
two-method contract:

```python
class Provider(Protocol):
    provider_id: ClassVar[str]
    def translate(self, segment: Segment, target_lang: str) -> ProviderResult: ...
    def supports(self, source_lang: str, target_lang: str) -> bool: ...
```

The Protocol lives at `ainemo.providers.base` and the stable id
constants at `ainemo.providers._ids`. The CLI's `--provider` flag
and the daemon's `translate` op accept any of the ids below.

| `provider_id` | Kind | Default model | Cost tracked | Status |
|---|---|---|---|---|
| `noop` | placeholder | — | no | always available |
| `nllb` | local NMT | `facebook/nllb-200-distilled-600M` | no | always available |
| `opus` | local NMT (OPUS-MT) | per-pair Helsinki-NLP model | no | always available |
| `openai` | managed LLM | `gpt-4o-2024-11-20` | yes | needs `OPENAI_API_KEY` |
| `anthropic` | managed LLM | `claude-sonnet-4-5-20250929` | yes | needs `ANTHROPIC_API_KEY` |
| `ollama` | local LLM (HTTP) | `llama3.2` | no (local) | needs running daemon |

All cloud providers run with **`temperature=0`** by default for
reproducibility (AGENTS.md § Architecture Rules). Override per
provider via the constructor; cycle-3 routes-config will surface
overrides through configuration.

---

## How a translation is recorded

Every `translate()` call returns a `ProviderResult` (kw-only frozen
dataclass) the router writes verbatim to the **UsageLog** at
`~/.ainemo/usage.jsonl` (override via `--usage-log`):

```python
@dataclass(frozen=True, kw_only=True)
class ProviderResult:
    target_text: str
    provider: str           # concrete backend id, e.g. "openai"
    model: str              # dated id where applicable
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    cost_usd: float | None
    confidence: float | None
```

`None` distinguishes "not measured" from zero (local providers
record `cost_usd=None`; cloud providers without a pricing-table
entry also record `cost_usd=None`).

Inspect the log with:

```bash
nemo provider stats                       # all-time aggregate
nemo provider stats --since 2026-05-01    # window by ISO timestamp
```

---

## Translation memory scoping

By default the CLI passes the requested `--provider` as
`expected_provider` to the pipeline, which forwards it into TM
lookups. This means `--provider openai` only sees rows produced
by openai, and a previous `--provider noop` run cannot silently
satisfy it. Pass a different `expected_provider` (or omit it for
"any cached translation" cycle-1 semantics) when wiring the
pipeline directly.

---

## `noop`

Pipeline-internal echo provider. Returns the source text unchanged
so the full pipeline (parse → TM → provider → validators →
serialize) runs without touching any model. Default for
`nemo translate` so the command works offline out of the box.

- **Prereqs:** none.
- **Env vars:** none.
- **Cost:** zero. Records to UsageLog like any other provider so
  cost surveillance is uniform.
- **Use cases:** smoke-testing the pipeline, CI runs that don't
  need real translations, fixture generation.

---

## `nllb` — Facebook NLLB-200

Local neural-machine-translation. Downloads the model on first use
(roughly 2.5 GB for the distilled-600M default; larger checkpoints
available).

- **Prereqs:** `transformers`, `torch`, `sacremoses`, `sentencepiece`
  (all in the base install). HuggingFace cache writable; no network
  required after first download.
- **Default model:** `facebook/nllb-200-distilled-600M`. Override
  via `NllbProvider(model="facebook/nllb-200-3.3B", ...)`.
- **Env vars:** none. Standard HuggingFace `HF_HOME` /
  `TRANSFORMERS_CACHE` apply if you want to relocate the cache.
- **Cost:** local execution; `cost_usd=None`, `input_tokens=None`,
  `output_tokens=None`. `latency_ms` is wall-clock.
- **Reproducibility:** beam-search defaults; the bundled wrapper
  uses `transformers.pipeline(task="translation", ...)` and does
  not currently expose a temperature knob.
- **Supported pairs:** any combination of these BCP-47 tags as
  source AND target (25 tags, 600 ordered pairs):
  `ar, de, el, en, es, fr, he, hi, it, iw, ja, ko, nl, pl, pt,
  ru, sv, th, tr, zh, zh-cn, zh-hans, zh-hant, zh-hk, zh-tw`.
  Region subtags strip to primary (`en-US` → `en`); `iw`/`he`
  both map to Hebrew; Chinese variants pin script (Simplified vs
  Traditional → different NLLB codes). Unknown pairs surface
  `ValueError` from `translate()` and `False` from `supports()`.

---

## `opus` — Helsinki-NLP OPUS-MT

Local pair-specific MarianMT. **English source only** in cycle 2;
cycle 3+ extends to other source languages by populating per-source
maps. Per-target HuggingFace repo: each `en→<target>` route loads
a different checkpoint.

- **Prereqs:** same as NLLB (`transformers`, `torch`,
  `sentencepiece`, `sacremoses`). Each target downloads a
  ~300 MB checkpoint on first use; the `MarianModelCache` keeps
  models warm across calls in one process.
- **Default model:** per-target. Romance group (`fr`, `it`, `pt`,
  `es`) shares `Helsinki-NLP/opus-mt-en-ROMANCE`; Germanic group
  (`de`, `nl`, `sv`) shares `Helsinki-NLP/opus-mt-en-gem`; Korean
  uses `Helsinki-NLP/opus-mt-tc-big-en-ko` (the standard
  `opus-mt-en-ko` is unusable). Single-language models cover the
  rest. Grouped models require a `>>{token}<<` prefix on the
  source text; the wrapper handles this transparently.
- **Env vars:** none.
- **Cost:** local; `cost_usd=None`, no token counts.
- **Reproducibility:** Marian generation defaults; no temperature
  knob exposed.
- **Supported targets (en →):** 21 tags:
  `ar, de, el, es, fr, he, hi, it, iw, ja, ko, nl, pl, pt, ru,
  sv, th, tr, zh, zh-cn, zh-hk`. Sources other than English
  return `False` from `supports()` and raise `ValueError` from
  `translate()` with a message pointing the caller at NLLB.

---

## `openai` — OpenAI Chat Completions

Managed LLM via the OpenAI Python SDK.

- **Prereqs:** `openai` (in the base install). Module import is
  side-effect-free; the SDK client is constructed lazily on the
  first `translate()` call so missing credentials surface there
  rather than at collection time.
- **Default model:** `gpt-4o-2024-11-20`. **Dated IDs only** —
  undated aliases (e.g. `gpt-4o`) shift behind the scenes and
  would break cost reproducibility. Override via
  `OpenAIProvider(model="gpt-4o-mini-2024-07-18", ...)`.
- **Env vars:**
  - `OPENAI_API_KEY` — required. Missing key raises
    `MissingOpenAiApiKey` with the env var name in the message.
- **Cost:** tracked. Pricing per 1M tokens (USD):

  | Model | Input | Output |
  |---|---:|---:|
  | `gpt-4o-2024-11-20` | $2.50 | $10.00 |
  | `gpt-4o-2024-08-06` | $2.50 | $10.00 |
  | `gpt-4o-mini-2024-07-18` | $0.15 | $0.60 |
  | `gpt-4-turbo-2024-04-09` | $10.00 | $30.00 |

  Models not in this table record `cost_usd=None` (not zero) — add
  the entry in `openai_provider.py` after verifying current
  pricing at <https://platform.openai.com/docs/pricing>.
- **Reproducibility:** `temperature=0`, `top_p=1.0`,
  `frequency_penalty=0`, `presence_penalty=0`. `max_tokens=2000`
  default (override via `OpenAIProvider(max_tokens=...)`).
- **Quote / whitespace handling:** the SDK occasionally wraps
  output in stray quotes despite the prompt forbidding it. The
  wrapper strips a quote pair **only when the source itself was
  not quoted** — so a button label like `"OK"` round-trips with
  quotes intact. A single trailing `\n` is stripped (SDKs
  sometimes append one); internal whitespace and leading/
  trailing-space padding (e.g. `" Submit "`) is preserved.
- **Supported pairs:** every BCP-47 pair we'd realistically use
  for software i18n; `supports()` returns `True` unconditionally
  in cycle 2.

---

## `anthropic` — Anthropic Messages

Managed LLM via the Anthropic Python SDK.

- **Prereqs:** `anthropic>=0.40` (declared in `pyproject.toml`).
  Same lazy-client pattern as OpenAI.
- **Default model:** `claude-sonnet-4-5-20250929`. Sonnet over
  Opus for translation cost; dated rather than alias per Anthropic
  docs convention. Override via
  `AnthropicProvider(model="claude-3-5-haiku-20241022", ...)`.
- **Env vars:**
  - `ANTHROPIC_API_KEY` — required. Missing key raises
    `MissingAnthropicApiKey`.
- **Cost:** tracked. Pricing per 1M tokens (USD):

  | Model | Input | Output |
  |---|---:|---:|
  | `claude-sonnet-4-5-20250929` | $3.00 | $15.00 |
  | `claude-opus-4-1-20250805` | $15.00 | $75.00 |
  | `claude-3-5-sonnet-20241022` | $3.00 | $15.00 |
  | `claude-3-5-haiku-20241022` | $0.80 | $4.00 |

  Verify current pricing at <https://docs.anthropic.com/en/docs/about-claude/pricing>
  before touching the table.
- **API differences from OpenAI:** the Messages API takes the
  system prompt as a top-level kwarg (not as a chat message), and
  responses come back as a list of content blocks. The wrapper
  walks to the first `text` block; non-text blocks (e.g. future
  `tool_use` for termbase enforcement) raise a clear error rather
  than silently returning empty.
- **Reproducibility:** `temperature=0`, `max_tokens=2000` default.
- **Quote / whitespace handling:** identical contract to the
  OpenAI provider — same conditional unwrap, same trailing-newline
  rule. Cross-provider tests pin both.
- **Supported pairs:** every BCP-47 pair; `supports()` returns
  `True` unconditionally.

---

## `ollama` — local Ollama daemon

Local LLM via the official `ollama` Python SDK against a running
Ollama daemon. Local-first answer for users who want LLM-quality
translation without a HuggingFace download or a cloud API bill.

- **Prereqs:** `ollama>=0.4` Python package, plus a running Ollama
  daemon and the requested model pulled locally
  (`ollama pull llama3.2`). Daemon defaults to
  `http://localhost:11434` (the upstream `ollama serve` default).
- **Default model:** `llama3.2`. Override via
  `OllamaProvider(model="qwen2.5", ...)` or routes-config in
  cycle 3.
- **Env vars:**
  - `OLLAMA_HOST` — alternate daemon URL. Constructor `host=`
    arg overrides the env var.
- **Cost:** local execution; `cost_usd=None` always. Token counts
  come from `prompt_eval_count` / `eval_count` when the model
  populates them; older or modified models may not, in which case
  both are `None` (the UsageLog distinguishes "not measured" from
  zero).
- **Reproducibility:** `temperature=0` passed via the SDK's
  `options=` kwarg.
- **Quote / whitespace handling:** identical contract to OpenAI /
  Anthropic.
- **Supported pairs:** depends on the locally-pulled model;
  `llama3.2` covers most BCP-47 pairs we'd realistically use.
  `supports()` returns `True` unconditionally — cycle-3+ may add
  per-model gating once benchmark data tells us which pairs are
  unsafe.

---

## Routing

`ProviderRouter` in `ainemo.providers.router` is the cycle-2 façade
the pipeline talks to. The router:

1. Picks a provider by matching `RoutingRule`s against
   `(source_lang, target_lang, persona, domain)` — first match
   wins, with `default_provider` as the fallback.
2. Calls the chosen provider's `translate()` with optional
   exponential-backoff retry (configured via `retry_exceptions`).
3. Patches missing `latency_ms` and missing `provider` self-
   attribution as defense-in-depth (cycle-2 P1 fix).
4. Records the full `ProviderResult` to UsageLog.

Cycle-2 fail-fast policy (per pitch open-question 7): if no
routing rule matches and the configured default isn't registered,
or if the selected provider's `supports()` returns `False`, the
router raises rather than silently falling back to a different
backend. Users who want fallback set it explicitly via
`--provider` or a routes-config rule.

The CLI's single-`--provider` mode wraps the chosen backend in a
one-rule `RoutingConfig(default_provider=<id>)`; the daemon caches
one router per `provider` id seen during a session.

---

## Adding a new provider

1. Create a sibling package under `src/ainemo/providers/<id>/`.
2. Add the id constant to `_ids.py`.
3. Implement `<id>_provider.py` with a class satisfying the
   Protocol. Lazy SDK construction lives in `_client.py` (so
   module import never reads env vars or hits the network).
4. Pin a dated default model + a pricing table for cloud
   backends. Local backends record `cost_usd=None`.
5. Implement quote / whitespace handling matching the contract:
   strip a single trailing `\n`; conditional quote-pair unwrap
   only when the source was unquoted. Cross-provider tests pin
   the exact rule.
6. Add the provider to `cli/commands.py:_build_provider` and the
   `_PROVIDER_CHOICES` tuple. Module import stays cheap via local
   import inside `_build_provider`.
7. Ship per-provider unit tests covering Protocol conformance,
   attribution, temperature 0, quote/whitespace round-trips,
   pricing edge cases, missing-credential handling, and empty/
   malformed responses.
