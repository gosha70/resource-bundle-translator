---
pitch_id: 0002-providers-gradle
title: "Cycle 2 — Provider Abstraction + Gradle Plugin"
appetite: 6w
bet_status: shipped
cycle: "02"
circuit_breaker: "If Half B (Gradle plugin — scopes 10–13) is still uphill at week 4, ship Half A (provider migration + UsageLog + nemo daemon) only and shelve the Gradle plugin into cycle 6's multi-platform expansion."
shaped_by: gosha70
shaped_date: 2026-05-03
---

# Cycle 2 — Provider Abstraction + Gradle Plugin

<!-- Human-readable header. Authoritative status / dates are in the YAML
     frontmatter above; this list is for at-a-glance reference and stays
     load-bearing in cross-links from the README and ROADMAP. -->

- **ID**: 0002
- **Appetite**: 6w (wall-clock ceiling; actual session execution ≪ appetite)
- **Status**: shipped
- **Owner**: gosha70
- **Shipped**: 2026-05-05 via [PR #7](https://github.com/gosha70/resource-bundle-translator/pull/7), squash-merge commit `ac30b3e`. Retrospective: [`specs/retros/cycle-2.md`](../../retros/cycle-2.md). All 15 hill scopes done.

## Problem

Today (post cycle 1) AI-NEMO has a clean translation pipeline: bundle adapters, segment-keyed TM, ICU-aware validators, and a `Provider` Protocol skeleton. What it does **not** have is a real provider ecosystem behind that Protocol — every backend (NLLB, OPUS, OpenAI) is a moved-as-is legacy class from cycle 0's `_legacy/`-adjacent `providers/` tree, and the user has no way to swap or compare them. AGENTS.md § Provider Rules promised "every LLM call wrapped with cost + latency tracking, recorded to `~/.ainemo/usage.jsonl`" — none of that exists yet. Anthropic Claude and Ollama backends are also missing entirely, which makes AI-NEMO a non-starter for users who want a managed cloud option that isn't OpenAI, or a local-first option that isn't a HuggingFace download.

The second half of cycle 2 is the **first build-tool plugin**. AI-NEMO's strategic positioning (per ROADMAP § "Strategic positioning") rests on being **build-tool-native**, not server-shaped. A user with a Gradle JVM project should be able to add a plugin, declare their `messages_*.properties` source, run `./gradlew translateBundles`, and get translated output during their normal build — no separate CLI, no Python virtualenv to manage. PhilKes already covers Android `strings.xml`; the gap is JVM `messages_*.properties` + Spring Boot resource bundles.

Three concrete pain points this cycle resolves:

1. **No Provider Protocol is actually filled in.** Cycle 1's `core.providers.Provider` is a Protocol stub. Every concrete backend extends a different ABC (`TranslatorModel` from the legacy tree). Translation routing today picks whichever backend the CLI flag named — no router, no cost tracking, no fallback policy.
2. **Closed-shop provider list.** Anthropic Claude is widely used and absent. Ollama is the obvious local-first answer for users without GPUs and absent. Adding either requires more than just writing a class — the Protocol needs to actually be the thing both new and existing backends implement.
3. **No build-tool integration.** A localization pipeline that requires `python -m ainemo.cli.translate ...` is a non-starter for JVM teams whose CI is already Gradle-shaped. T-Ragx and Weblate both lose enterprise users on this exact friction.

This pitch tackles the three together because the build-tool plugin is only useful **after** the provider abstraction is real. A Gradle plugin that delegates to a single hard-coded provider is just as locked-in as the legacy CLI.

## Solution shape

```
┌─ Gradle build (cycle 2.B)  ─────────────────────────────────────┐
│                                                                  │
│   plugins { id("com.egoge.ai.nemo.translate") }                  │
│   aiNemoTranslate {                                              │
│     source = "src/main/resources/messages_en_US.properties"      │
│     targetLangs = ["de", "fr", "es"]                             │
│     provider = "claude"                                          │
│   }                                                              │
│                                                                  │
│   ./gradlew translateBundles                                     │
│        │                                                         │
│        ▼ JSON-over-stdio                                         │
│                                                                  │
│   nemo daemon  ◄──── (Python, started by plugin worker)          │
│        │                                                         │
│        ▼                                                         │
└────────┼─────────────────────────────────────────────────────────┘
         │
         ▼
┌─ Python core (cycle 2.A) ──────────────────────────────────┐
│                                                             │
│  TranslationPipeline (cycle 1) ──► ProviderRouter ──► …     │
│                                       │                     │
│                                       ▼                     │
│              ┌──────────────────────────────────────┐       │
│              │  Provider Protocol (cycle 1, filled) │       │
│              │   ├─ NllbProvider                    │       │
│              │   ├─ OpusProvider                    │       │
│              │   ├─ OpenAIProvider                  │       │
│              │   ├─ AnthropicProvider   (NEW)       │       │
│              │   └─ OllamaProvider      (NEW)       │       │
│              └──────────────────────────────────────┘       │
│                                       │                     │
│                                       ▼                     │
│              ┌────────────────────────────────────┐         │
│              │  UsageLog (~/.ainemo/usage.jsonl)  │         │
│              │  per call: provider, model, tokens │         │
│              │            latency_ms, cost        │         │
│              └────────────────────────────────────┘         │
└─────────────────────────────────────────────────────────────┘
```

Cycle 2 has two halves that have to ship together — **2.A: provider plumbing** lands first as the foundation; **2.B: Gradle plugin** is meaningless without 2.A but motivates a clean Protocol.

### Interfaces (SDD layer)

**`src/ainemo/providers/base.py`** (cycle 2 finalizes the Protocol — cycle 1 introduced a stub)

```python
class Provider(Protocol):
    provider_id: ClassVar[str]                    # "openai", "anthropic", "ollama", "nllb", "opus"

    def translate(
        self,
        segment: Segment,                         # from cycle 1's core.segment
        target_lang: str,
    ) -> ProviderResult: ...

    def supports(self, source_lang: str, target_lang: str) -> bool: ...

@dataclass(frozen=True)
class ProviderResult:
    target_text: str
    model: str                                    # whatever string the provider's API accepts as a model id; e.g. NLLB's "nllb-200-distilled-600M", a dated Anthropic ID like "claude-sonnet-4-20250514", an OpenAI ID like "gpt-4o-2024-11-20", or whatever Ollama tag is locally pulled.
    input_tokens: int | None                      # None for non-LLM providers (NLLB/OPUS — token counts irrelevant)
    output_tokens: int | None
    latency_ms: int
    cost_usd: float | None                        # None for local providers (NLLB/OPUS/Ollama)
    confidence: float | None                      # None unless the provider exposes it
```

**`src/ainemo/providers/router.py`**

```python
class ProviderRouter:
    """Single entry point for every provider call. Records usage; applies
    routing rules; orchestrates retry. Pipeline calls only the router —
    never a provider directly."""

    def __init__(
        self,
        providers: Mapping[str, Provider],        # provider_id -> instance
        routing_config: RoutingConfig,
        usage_log: UsageLog,
    ): ...

    def translate(self, segment: Segment, target_lang: str) -> ProviderResult: ...

@dataclass(frozen=True)
class RoutingConfig:
    """Rules: which provider for which (source_lang, target_lang, persona)?
    Loaded from YAML, never hardcoded."""
    default_provider: str
    rules: list[RoutingRule]

@dataclass(frozen=True)
class RoutingRule:
    provider_id: str
    source_lang: str | None                       # None = any
    target_lang: str | None
    persona: str | None
    domain: str | None
```

Routing config lives in `src/ainemo/providers/config/routes.yaml` (constant default; user can override via `--routes` flag or per-project file).

**`src/ainemo/providers/_usage_log.py`**

```python
class UsageLog:
    """Append-only JSONL writer for per-call usage records. One record
    per provider invocation; never silent."""

    def __init__(self, path: Path = DEFAULT_USAGE_LOG_PATH): ...
    def record(self, *, provider: str, model: str, input_tokens: int | None,
               output_tokens: int | None, latency_ms: int, cost_usd: float | None,
               source_lang: str, target_lang: str, segment_fingerprint: str) -> None: ...
    def stats(self, since: datetime | None = None) -> UsageStats: ...
```

`DEFAULT_USAGE_LOG_PATH = Path.home() / ".ainemo" / "usage.jsonl"` (per AGENTS.md § Provider Rules).

**`src/ainemo/providers/_retry.py`**

```python
def with_retry(
    fn: Callable[..., T],
    *,
    max_attempts: int = MAX_RETRY_ATTEMPTS,        # 3 per AGENTS.md
    backoff_base_seconds: float = BACKOFF_BASE_SECONDS,
    rate_limit_exceptions: tuple[type[Exception], ...],
) -> T: ...
```

Single source of truth for exponential-backoff retry across providers. Per-provider modules pass their SDK's rate-limit exception types.

**Concrete providers** (one module each, all implementing `Provider`):

| Module | Class | Notes |
|---|---|---|
| `providers/nllb/nllb_provider.py` | `NllbProvider` | Local. Reuses cycle-0 weights. `cost_usd=None`. |
| `providers/opus/opus_provider.py` | `OpusProvider` | Local. MarianMT. `cost_usd=None`. |
| `providers/openai/openai_provider.py` | `OpenAIProvider` | Lazy client init (cycle-0 audit pattern). `temperature=0`. |
| `providers/anthropic/anthropic_provider.py` | `AnthropicProvider` | **NEW.** Anthropic SDK Messages API. `temperature=0`. Uses prompt caching for the system prompt + glossary. |
| `providers/ollama/ollama_provider.py` | `OllamaProvider` | **NEW.** Local Ollama HTTP client. `temperature=0`. `cost_usd=None`. |

Each provider has a sibling `_client.py` for SDK-client construction (lazy, takes config) and a sibling `_prompts.py` for prompt-template constants (no inline literals). System prompts and glossary-injection templates live as constants per the project's *No magic strings/numbers — named constants always* rule (AGENTS.md § Prohibited Patterns).

**`src/ainemo/cli/daemon.py`** (cycle 2's CLI gains a real subcommand)

```python
class DaemonProtocol:
    """JSON-over-stdio. Versioned envelope.

    Request:  {"v": "1", "op": "translate", "segment": {...}, "target_lang": "de"}
    Response: {"v": "1", "ok": true, "result": {...}} or {"ok": false, "error": "..."}
    Shutdown: {"v": "1", "op": "shutdown"}
    """
```

Daemon process is single-threaded; concurrent requests serialize. The Gradle plugin spawns one daemon per build (re-uses across `translateBundles` task invocations), tears it down at build end.

**`gradle-plugin/`** (new top-level module — Kotlin DSL)

```
gradle-plugin/
├── build.gradle.kts
├── settings.gradle.kts
└── src/
    ├── main/kotlin/com/egoge/ainemo/translate/
    │   ├── AiNemoTranslatePlugin.kt       # plugin entry
    │   ├── AiNemoTranslateExtension.kt    # DSL
    │   ├── TranslateBundlesTask.kt        # the task users run
    │   ├── DaemonClient.kt                # spawns `nemo daemon`, JSON-over-stdio
    │   └── PythonRuntimeLocator.kt        # finds the Python venv with ainemo installed
    └── functionalTest/kotlin/             # Gradle TestKit
        └── AiNemoTranslateFunctionalTest.kt
```

Plugin Maven coordinates: **`com.egoge.ai.nemo:translate-gradle-plugin`** per AGENTS.md § Reference. Published to the Gradle Plugin Portal as `com.egoge.ai.nemo.translate`.

## Rabbit holes

- **Don't reimplement core translation logic in the Gradle plugin.** Plugin = thin façade. ALL translation goes through the daemon → Python core. AGENTS.md § Architecture Rules: "library-first, CLI-second, build-tool-plugin-third." Two implementations of placeholder preservation will diverge within a release.
- **Don't switch from JSON-over-stdio to gRPC without benchmark evidence.** JSON over a pipe is plenty for build-time translation throughput. gRPC adds protoc tooling, generated code, and dependency weight for zero observable benefit at this volume. Revisit only if a real Gradle TestKit benchmark shows IPC dominating wall time.
- **Don't add streaming responses for OpenAI/Anthropic.** Translation is a single request-response per segment; streaming the model output adds chunked-decode complexity for no UX gain (the segment is invisible to the user mid-build).
- **Don't auto-discover providers via Python entry points.** Concrete dict-based registration in `providers/__init__.py` is enough. Plugin discovery is cycle 6+ scope (when external pack/provider authors exist).
- **Don't build a fancy routing DSL.** YAML rules with provider-id + lang-pair + persona/domain matching are sufficient. Programmable routing (lambda functions in config, etc.) is a footgun.
- **Don't bikeshed namespaces.** Maven group `com.egoge.ai.nemo`, plugin id `com.egoge.ai.nemo.translate` per AGENTS.md § Reference. If contested at /bet, surface as a question; otherwise assume locked.
- **Don't build a Maven plugin or npm plugin in this cycle.** Cycle 6.

## No-gos

- No Maven plugin. (Cycle 6.)
- No npm / Vite plugin. (Cycle 6.)
- No Android `strings.xml` adapter. (PhilKes covers it.)
- No `.xcstrings` / Fluent / `.resx`. (Cycle 6.)
- No KG / Kuzu / termbase work. (Cycle 3.)
- No domain packs. (Cycle 4.)
- No reviewer web UI. (Cycle 5.)
- No fine-tuning, no custom checkpoint training. (Use Ollama with a local checkpoint as the escape hatch.)
- No multi-format support beyond what cycle 1 already shipped (`.properties`, i18next JSON, gettext `.po`, XLIFF 2.0). The Gradle plugin targets `.properties` only in this cycle.
- No telemetry-on-by-default. UsageLog is local; no phone-home.

## Scopes

> Estimates are session-execution time, not human-developer-days (project rule: *Calibrate estimates for Claude Code, not human-days*). Total cycle 2 execution is hours, not weeks; the 6-week appetite is wall-clock willingness to wait.

**Half A — Provider plumbing (the foundation):**

1. **`Provider` Protocol finalized + `ProviderResult` data model** — fill in cycle 1's stub. Constants for provider IDs (`PROVIDER_OPENAI`, `PROVIDER_ANTHROPIC`, etc.) in `providers/_ids.py`. Unit tests pin Protocol contract via a `MockProvider`.
2. **`UsageLog` (`providers/_usage_log.py`)** — JSONL append, lock-free single-writer (build-time tool, no concurrent writers). `~/.ainemo/usage.jsonl` default path constant. `nemo provider stats` CLI surfaces it. Unit tests on a tmp_path.
3. **`with_retry` (`providers/_retry.py`)** — exponential backoff, configurable max attempts, exception-type allow-list. Unit tests with synthetic rate-limit exceptions.
4. **`ProviderRouter` (`providers/router.py`)** — config-driven routing, default provider, per-rule precedence. Records every call to UsageLog. Unit tests cover precedence, fallback to default, rate-limit retry path. Routing config schema in `providers/config/routes.yaml`.
5. **Migrate existing providers to the Protocol**: NLLB, OPUS, OpenAI. Each gets a sibling `_client.py` (lazy SDK-client construction) and `_prompts.py` (prompt-template constants). Delete the legacy `TranslatorModel` ABC. Delete `_legacy/` data modules + the 4 top-level shims (cycle-0 carryover). Update CLI to call the router. Existing cycle-1 integration tests should keep passing.
6. **Add `AnthropicProvider`** — `providers/anthropic/`. Uses Anthropic SDK; prompt caching for system prompt + glossary; `temperature=0`. Unit tests (mocked SDK) + integration test gated on `ANTHROPIC_API_KEY`.
7. **Add `OllamaProvider`** — `providers/ollama/`. Local HTTP client; `temperature=0`; default model id is a /bet-time decision (open question 5), held in `providers/ollama/_models.py` as a named constant — never inlined. Unit tests + integration test gated on a running Ollama daemon.
8. **`nemo provider` CLI subcommand** — `nemo provider list` (registered providers + their availability), `nemo provider stats [--since DATE]` (UsageLog summary). Argparse-based; idiomatic `--help`.

**Half B — Gradle plugin:**

9. **Daemon mode (`src/ainemo/cli/daemon.py`)** — `nemo daemon` reads JSON-over-stdio. Versioned envelope. Single-threaded, serialized requests. Graceful shutdown. Unit tests via subprocess + protocol fixture.
10. **`gradle-plugin/` skeleton** — Kotlin DSL plugin module, build.gradle.kts wiring, plugin entry, DSL extension, basic Gradle TestKit smoke test. Maven coordinates `com.egoge.ai.nemo:translate-gradle-plugin`. Plugin id `com.egoge.ai.nemo.translate`.
11. **`TranslateBundlesTask` + `DaemonClient`** — task spawns the Python daemon, sends JSON requests for each segment of the source bundle, receives results, writes target files. `PythonRuntimeLocator` finds the AI-NEMO venv (configurable via `pythonExecutable` in the DSL). Functional test runs end-to-end on a real `messages_en_US.properties` fixture with mocked daemon.
12. **Functional test against real daemon** — TestKit functional test starts a real `nemo daemon` (NLLB provider, no network), translates a 5-segment `.properties` bundle to one target language, asserts output file exists and round-trips through cycle-1 adapter.
13. **Plugin Portal publishing setup** — `build.gradle.kts` configures `gradle.publish.key` / `gradle.publish.secret` env-var-driven publishing to https://plugins.gradle.org/. Documentation (under `gradle-plugin/README.md`) covers `./gradlew publishPlugins` from a clean state. **Actual publish is a manual step** at cycle close, gated on the user's Gradle Portal credentials — automation lands in a future cycle.

**Cross-cutting:**

14. **Benchmarks** — `tests/benchmarks/cycle-2-providers.md`: cost-per-segment + p50/p95 latency for each provider on a 50-segment fixture corpus, en→{de,fr,es,iw}. Manual run (gated on real API keys); results checked into the file as a snapshot.
15. **Documentation** — `docs/providers.md` (provider matrix, routing config, env vars), `docs/gradle-plugin.md` (plugin install, DSL reference, troubleshooting). README updated with a "Gradle plugin" section.

Slack budget: 2–3 scope-equivalents for IPC bug-hunting (the daemon is the most novel surface), provider-API surprises (Ollama's HTTP API has changed historically), and Gradle TestKit flakiness on CI.

## Test strategy

**Unit** (per-module, fast, deterministic):
- Each provider mocked at the SDK boundary; assert `ProviderResult` fields, retry behavior, prompt construction.
- `ProviderRouter`: precedence rules; default fallback; usage-log persistence; retry orchestration.
- `UsageLog`: JSONL round-trip; stats aggregation; concurrent-write semantics (single writer, append-only).
- `with_retry`: backoff math; exception allow-listing; success-on-third-attempt path.
- `DaemonProtocol`: envelope round-trip; version mismatch detection; graceful shutdown.

**Integration** (per-cycle CI, marked `integration`):
- Each cloud provider gated on env-var presence (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`); skip with notice otherwise.
- Ollama: gated on `OLLAMA_HOST` env var; skip otherwise.
- Daemon end-to-end: `subprocess.Popen` of `nemo daemon`, send N requests, assert results + timing.

**Contract** (the SDD enforcement layer):
- Every provider ships a `test_contract.py` exercising the same `ProviderContract` matrix: handles known languages, raises on unsupported pairs, populates ProviderResult invariants, respects `temperature=0` reproducibility (mock-checked), records to UsageLog, retries on synthetic rate limits.

**Gradle TestKit** (functional):
- `gradle-plugin/src/functionalTest/`: runs a real Gradle build with the plugin applied against a fixture project, spawns a real daemon, asserts output `.properties` files materialize and round-trip through cycle-1's `JavaPropertiesAdapter`.

**Benchmark** (manual, per cycle):
- Cost per segment + p50/p95 latency on a 50-segment corpus en→{de,fr,es,iw}, all 5 providers (where API keys / local daemons available).
- Daemon throughput: N segments/sec via stdio at the sustained rate.

**Acceptance criteria — cycle is "done" when**:
- `Provider` Protocol filled; legacy `TranslatorModel` ABC and `_legacy/` removed; cycle-0 deprecation shims deleted.
- All 5 providers (NLLB, OPUS, OpenAI, Anthropic, Ollama) implement the Protocol; all pass the contract test matrix.
- `ProviderRouter` records every call to `~/.ainemo/usage.jsonl`; `nemo provider stats` reads the log.
- `nemo daemon` works via JSON-over-stdio; protocol versioned.
- Gradle plugin builds, tests pass via TestKit, plugin can be `publishPlugins`-published from a clean checkout (manual gate on user's portal creds).
- Benchmark snapshot in `tests/benchmarks/cycle-2-providers.md` checked in.
- CI green: ruff + format + mypy strict + pytest on Python 3.10/3.11/3.12; Gradle TestKit green on JDK 17 + 21.
- Documentation updated: `docs/providers.md`, `docs/gradle-plugin.md`, README.

## Open questions

These are pre-resolved from AGENTS.md / ROADMAP / cycle-0 conventions per the project's *Pre-resolve "open questions" from project docs before asking the user* rule. Recorded here for /bet-time confirmation.

1. **Plugin Maven coordinates** → `com.egoge.ai.nemo:translate-gradle-plugin`, plugin id `com.egoge.ai.nemo.translate`. Per AGENTS.md § Reference. Confirmed unless user specifies otherwise.
2. **Daemon IPC protocol versioning** → semver in the JSON envelope (`{"v": "1", ...}`). Concrete-in-code, evolves additively. Pure pinned-hash versioning is too rigid for an IPC surface that ships with the package.
3. **Caching layer placement** → at the **router** (above providers), keyed by `(segment.fingerprint, target_lang, persona, model_id)`. Misses fall through to the chosen provider. Per AGENTS.md § Translation Memory Rules ("TM is the first stop, not the last"). Cycle-1 TM and cycle-2 router cache are the **same** SQLite table — the router checks before invoking the provider.
4. **Anthropic / OpenAI default model IDs** → resolved at build time:
   - Anthropic default: `claude-sonnet-4-5-20250929` (Sonnet 4.5 dated ID) — Sonnet over Opus for translation cost; dated rather than alias per Anthropic docs convention.
   - OpenAI default: `gpt-4o-2024-11-20` (current GPT-4o snapshot at build time).
   Both held as `_DEFAULT_MODEL` constants in `providers/<vendor>/_models.py`; never inlined. Override via `routes.yaml`. Cycle 4+ benchmarking may reconsider.
5. **Ollama default model** → resolved at build time: **`llama3.2`** (current Ollama default; users override via `routes.yaml` for `qwen`, `gemma`, etc.). Constant in `providers/ollama/_models.py`.
6. **Plugin Portal publish automation** → manual at cycle close. CI verification stops at "build + test + publishPlugins dry-run." Actual publish needs the user's portal credentials and is a deliberate human gate.

Genuinely contested at /bet (surface for the user):

7. **Provider routing strategy when no rule matches and no creds for the configured default** → resolved at /bet: **fail fast (raise)**. Silent fallback to a different model class (NMT vs LLM) breaks reproducibility and surprises users at translation-quality time. Users who want fallback set it explicitly via `--provider nllb` or a `routes.yaml` rule.

After /bet, no new questions allowed. Anything that surfaces during build goes to the cycle-3 cooldown shaping queue.

## Risks

- **Anthropic SDK API stability.** The Messages API and the `anthropic` Python client have evolved over 2024–2026. Pin a version range in `pyproject.toml` and add a `temperature=0` regression test to catch behavioral drift early.
- **Ollama HTTP API surface variation.** Different Ollama versions expose slightly different chat-completion endpoints. Pin a tested version range in `pyproject.toml`; document the expected `OLLAMA_HOST` contract.
- **Gradle TestKit flakiness.** TestKit spawns real Gradle daemons; can flake on slow CI runners. Mitigation: pin Gradle version, set `--no-daemon` for the test runs themselves (but we DO use the AI-NEMO daemon — different "daemon").
- **Daemon-mode IPC bugs.** Pipes block on full buffers; protocol parsing must be line-delimited and resilient to partial reads. Mitigation: use `\n`-delimited JSON, strict parsing, comprehensive error envelope.
- **Cost-tracking accuracy.** OpenAI/Anthropic SDKs return token counts in their response objects; Ollama doesn't always. For Ollama, `input_tokens=None, output_tokens=None, cost_usd=None` and document why in `docs/providers.md`.
- **Cycle-1 TM ↔ cycle-2 router cache collision.** The TM stores translations; the router cache wraps them. They MUST share the same store and key schema or we double-cache. Per open question 3 — the router checks the TM before invoking the provider; same SQLite table, same `(fingerprint, target_lang, provider, model)` primary key.

## What this cycle does NOT do

(Intentionally redundant with No-gos, but worth restating in plain language for the /bet table.)

- It does not ship any new domain knowledge — the providers are commodity backends, not termbase or persona work.
- It does not add new bundle formats — the cycle-1 four (`.properties`, JSON, `.po`, XLIFF) stay the canonical set.
- It does not ship a Maven or npm plugin — Gradle is the only build-tool integration this cycle.
- It does not add a UI surface — the `nemo` CLI gains `provider list` / `provider stats` / `daemon` subcommands, but no web admin / reviewer pages.
- It does not auto-publish to the Gradle Plugin Portal — that's a manual cycle-close step.

## Hill-chart bootstrap

After the user's `/bet 0002-providers-gradle`, `/cycle-start` initializes `specs/pitches/0002-providers-gradle/hill.json` with all 15 scopes uphill. Goal: every scope past the top of the hill by week 3 of the appetite (per `specs/README.md` cadence).

## Build branch convention

`cycle-2/providers-gradle` off the post-cycle-1 main. Build phase is one branch, one PR (project rule: *Fold the pitch into the cycle's build PR — no separate planning PRs*). PR title: "cycle-2: provider abstraction + Gradle plugin".
