# Validators

Validators inspect a `(Segment, TranslatedSegment)` pair and report issues. The pipeline runs every configured validator on every translation; **error**-severity violations block the segment from being written, **warning**-severity violations are surfaced in the run summary but don't block.

## Severity policy

| Severity | When to raise | Pipeline behavior |
|---|---|---|
| `error` | Translation is broken in a way the app will crash on or display incorrectly. Examples: dropped placeholder, malformed ICU. | Segment **not** written to the output file. **Not** stored in the TM. |
| `warning` | Translation works but has a UX concern. Example: target text exceeds a max-length budget. | Segment written; warning logged for human review. The cycle-5 reviewer UI surfaces these. |

The CLI flag `--strict` escalates warnings to blocking errors — useful for CI runs that want zero-warning builds.

## Cycle-1 validators

### `PlaceholderParityValidator` — severity: error

The most common LLM translation bug: dropping or inventing a placeholder.

```
Hello {name}!  →  Bonjour !          ← FLAGGED (lost {name})
Click {0}      →  Cliquez {99}       ← FLAGGED (invented {99})
{a}, {b}!      →  {b}, {a}!          ← OK (order can shift)
```

The validator compares the **bag** of `(kind, raw)` tuples between source and target. Order doesn't matter (positions can shift in translation); counts do (so missing or extra repetitions both fire).

### `IcuSyntaxValidator` — severity: error

Catches malformed ICU MessageFormat in the target text:

- **Unbalanced braces** — `Hallo {oops` or `Hallo oops}`.
- **Missing `other` branch** — every plural/select/selectordinal must have the spec-required catch-all. `{count, plural, one {…} few {…}}` (no `other`) → flagged.
- **Branch decomposition failure** — placeholder marked as ICU but the body can't be parsed.

### `LengthBudgetValidator` — severity: warning

Reads `Segment.metadata["max_length"]` (set by adapters that expose a length cap, e.g. XLIFF's `<unit maxBytes="…">`) and warns when the target exceeds it.

```python
seg = Segment(
    key="button.submit",
    source_text="OK",
    source_lang="en-US",
    metadata={"max_length": "10"},
)
# Target "Konfigurieren" → warning: 13 > 10
```

Tolerant of malformed `max_length` metadata (non-int): silent skip rather than crash the run.

### `ForbiddenTermsValidator` — severity: error

Constructed with a tuple of forbidden terms (brand names, trademarks, regulatory red flags). Flags every occurrence with a target-text span offset for reviewer-UI highlighting.

```python
v = ForbiddenTermsValidator(
    forbidden_terms=("Coca-Cola", "Microsoft"),
    case_insensitive=True,
    word_boundary=True,
)
```

**Defaults**
- `case_insensitive=True` — matches `coca-cola` and `Coca-Cola` alike.
- `word_boundary=True` — `"AI"` flags `" AI "` but not `"Aimee"`. Useful when the term is a normal word that should be preserved verbatim. Set `word_boundary=False` when the term is a brand stem you want flagged in any compound (`"BrandX"` should flag `"BrandXLite"`).

## Adding a new validator

1. Create `src/ainemo/core/validators/<name>.py`.
2. Implement the `Validator` Protocol: `name: ClassVar[str]`, `severity: ClassVar`, `check(source, translated) -> tuple[Violation, ...]`.
3. Add a section to `tests/unit/test_validators.py` with passing path + each kind of violation.
4. Register in `src/ainemo/cli/commands.py:_build_validators` if the validator should be on by default.

## Severity selection guidance

If you're not sure whether a new validator should be `error` or `warning`, ask:

> If this validator fires and the translation lands in production, **does the application break or display wrong information**?

- **Yes** → `error`. Block the write.
- **No, but it's still wrong** → `warning`. Log it.

Cycle-1 examples mapped:
- Placeholder parity → app crashes / loses dynamic data → **error**.
- ICU syntax → app crashes when rendering → **error**.
- Length budget → UI looks bad but app works → **warning**.
- Forbidden terms → legal/brand compliance, not technical → **error** (the typical use case is "do not let this ship without human review").
