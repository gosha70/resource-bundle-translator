# Personas

A **persona** is a configuration record that selects how a translation provider should *speak*. It carries a free-text `prompt_addendum` injected into the provider's system prompt, an optional register tag (`formal` / `casual` / `neutral`), an optional `domain_id` that narrows termbase lookups, an optional list of `forbidden_terms` consumed by `ForbiddenTermsValidator`, and optional `glossary_overrides` that win over termbase hits.

Personas are the cycle-3 substrate for "translate this for a software UI" vs "translate this for a legal contract" — same model, same router, different prompt shape. Cycle 4's domain packs (`legal-en`, `medical-en`, ...) ship persona YAML files alongside their concept data.

## YAML schema

The schema is enforced by Pydantic v2 with `extra="forbid"` — unknown keys fail load rather than silently lose data.

```yaml
# Mandatory fields (Pydantic raises if any of these are omitted):
persona_id: software-ui          # filename stem must match
name: "Software UI"
forbidden_terms: []              # may be empty; omitted ≠ empty
prompt_addendum: |
  Free-text block appended to the provider system prompt.

# Optional fields (defaults shown):
domain_id: software              # FK to a Domain row; null when persona is domain-agnostic
register: neutral                # one of: formal | casual | neutral | null
style_guide_url: null
glossary_overrides: []
```

`glossary_overrides` is a list of `{source_term, target_lang, target_term}` records — domain-pack-supplied bindings that override termbase lookups. Cycle-3 ships the schema and storage; cycle-5 reviewer UI surfaces overrides for editing.

The dropped-at-/bet `provider_hints` field is intentionally absent. Persona-aware routing lives in cycle-2's `RoutingConfig.persona` / `.domain` matchers — duplicating it on the persona schema would create two places that can disagree, with no clear "which wins?" semantics. Routing rules pick **which** provider; the persona shapes **how** that provider speaks.

## Starter personas

The package ships three starter YAMLs under `src/ainemo/personas/`. `nemo termbase init` syncs them on first start (idempotent on re-call).

| `persona_id` | `register` | `domain_id` | Use it for |
|---|---|---|---|
| `software-ui` | neutral | software | UI strings, button labels, menu items, error messages. Addendum prescribes placeholder preservation + idiomatic target-locale software-ecosystem terminology + brevity to fit UI elements. |
| `formal` | formal | null | Legal, regulatory, medical, corporate communications. Addendum prescribes formal register, full sentences, polite second-person ("Sie", "vous"). |
| `casual` | casual | null | Consumer apps, marketing copy, onboarding flows. Addendum prescribes conversational tone, contractions, informal second-person ("du", "tu"). |

Read the actual addendum text in [`src/ainemo/personas/software-ui.yaml`](../src/ainemo/personas/software-ui.yaml), [`formal.yaml`](../src/ainemo/personas/formal.yaml), [`casual.yaml`](../src/ainemo/personas/casual.yaml).

## Authoring a project-specific persona

1. Create `personas/your-id.yaml` in your project (or anywhere — `nemo termbase init --persona-dir /path` accepts a custom directory).
2. The filename stem MUST match `persona_id`. A mismatch raises `PersonaLoadError` rather than landing a misnamed persona.
3. Populate the four mandatory fields. `forbidden_terms: []` is fine when there's nothing to forbid; omitting the field entirely is a load error.
4. Run `nemo termbase init --persona-dir /path/to/personas` to sync. Re-runs upsert.
5. Wire the persona into the daemon by setting `persona_id` on the request envelope (the cycle-3 daemon loads it from the termbase per request).

Example — a brand-protected casual persona:

```yaml
persona_id: my-saas-casual
name: "MySaaS Casual"
domain_id: software
register: casual
forbidden_terms:
  - "AI"          # must stay literal — never translated
  - "MySaaS"      # brand name; never translated/transliterated
prompt_addendum: |
  Translate UI strings for the MySaaS product. Use a friendly,
  casual register. Preserve every placeholder exactly. Refer to
  the product as "MySaaS" verbatim — never translate or
  transliterate the brand name.
glossary_overrides:
  - source_term: "Sign in"
    target_lang: "de-DE"
    target_term: "Einloggen"
```

## Prompt-injection mechanics

When the cycle-3 pipeline (`TranslationPipeline(termbase=..., persona=...)`) hits a TM-miss segment, it builds a system-prompt addendum:

```
{persona.prompt_addendum}

Glossary (apply to the segment if relevant):
- "login" → "Anmeldung"
- "logout" → "Abmeldung"
```

This addendum is appended (with a blank-line separator) to the provider's default `SYSTEM_PROMPT`. The combined message is the system prompt for that single call.

- `temperature=0` is preserved (AGENTS.md § Architecture Rules: *Reproducibility by default*).
- LLM providers (OpenAI / Anthropic / Ollama) consume the addendum.
- Seq2seq providers (NLLB / OPUS) accept-and-ignore — they have no system-prompt surface.
- TM hits short-circuit before the addendum is built, so cached translations stay byte-stable across persona changes.
- When `persona=None` AND `termbase=None`, the pipeline calls the provider with the cycle-2 `(segment, target_lang)` signature and is byte-identical to cycles 1+2.

## Routing integration

The pipeline threads `persona=persona_id` and `domain=persona.domain_id` to `ProviderRouter.translate()` so cycle-2 routing rules can match. A rule like:

```python
RoutingRule(provider_id="anthropic", persona="legal", domain="legal")
```

fires when the pipeline is constructed with a `Persona(persona_id="legal", domain_id="legal")`. Without this plumbing the rule would never match — see the cycle-3 S6 P2 fix and its regression test (`test_pipeline_threads_persona_and_domain_to_router`).

## ForbiddenTermsValidator integration

The cycle-1 `ForbiddenTermsValidator(forbidden_terms: tuple[str, ...])` constructor stays for backward compat. Cycle 3 adds:

```python
from ainemo.core.validators.forbidden import ForbiddenTermsValidator

validator = ForbiddenTermsValidator.from_persona(persona)
```

Equivalent to constructing directly from `persona.forbidden_terms`, with the same `case_insensitive=True` / `word_boundary=True` defaults. Cycle-4 domain packs are expected to populate `forbidden_terms` per-pack (e.g. `legal-en` adds the brand names of common opposing-counsel firms users want to leave verbatim).

## Daemon envelope

The `nemo daemon` request envelope (used by the Gradle plugin) accepts two optional cycle-3 fields:

```json
{
  "v": "1",
  "id": "...",
  "op": "translate",
  "params": {
    "key": "login.button",
    "source_text": "login",
    "source_lang": "en-US",
    "target_lang": "de-DE",
    "provider": "anthropic",

    "persona_id": "software-ui",
    "termbase_path": ".ainemo/termbase.kuzu"
  }
}
```

Both are additive on `v=1` — clients that omit them get cycle-1+2 behavior. An unknown `persona_id` returns `ERR_INVALID_PARAMS` so the caller learns the misconfiguration rather than silently falling back. The daemon caches the Kuzu termbase across requests so the per-open cost amortizes.

## See also

- [`docs/termbase.md`](termbase.md) — concept model, schema, TBX I/O, `nemo termbase` CLI.
- [`src/ainemo/personas/`](../src/ainemo/personas/) — the three starter YAMLs.
- [`src/ainemo/core/termbase/persona_loader.py`](../src/ainemo/core/termbase/persona_loader.py) — Pydantic schema, `load_personas`, `sync_personas_into_termbase`, `PersonaLoadError`.
- [`specs/pitches/0003-kuzu-termbase/pitch.md`](../specs/pitches/0003-kuzu-termbase/pitch.md) § Open questions Q2 — the persona-schema /bet decisions.
