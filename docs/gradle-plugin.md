# AI-NEMO Gradle plugin

Cycle-2 thin Gradle façade over the AI-NEMO Python daemon. Add the
plugin to a JVM-shaped build and translate one resource bundle into
N target languages at build time, with reproducible output
(provider `temperature=0`; segment-keyed translation memory).

| Coordinate | Value |
|---|---|
| Plugin id | `com.egoge.ai.nemo.translate` |
| Maven group | `com.egoge.ai.nemo` |
| Artifact | `translate-gradle-plugin` |
| Min Gradle | 8.5 |
| Min JDK | 17 |

---

## Apply

```kotlin
// settings.gradle.kts
pluginManagement {
    repositories {
        gradlePluginPortal()
    }
}

// build.gradle.kts
plugins {
    id("com.egoge.ai.nemo.translate") version "0.1.0"
}

aiNemoTranslate {
    sourceFile.set(file("src/main/resources/messages_en_US.properties"))
    sourceLanguage.set("en-US")
    targetLanguages.set(listOf("de-DE", "fr-FR", "ja-JP"))
    provider.set("openai")
}
```

```bash
./gradlew translateBundles
```

---

## DSL reference

The `aiNemoTranslate { ... }` extension exposes lazy Gradle
properties so configuration flows through the build cache and the
task's input fingerprint correctly.

| Property | Type | Default | Description |
|---|---|---|---|
| `sourceFile` | `RegularFileProperty` | — (required) | The bundle file to translate. Must exist at task execution. |
| `sourceLanguage` | `Property<String>` | `"en-US"` | BCP-47 source-language tag. |
| `targetLanguages` | `ListProperty<String>` | — (required) | BCP-47 target tags, e.g. `["de-DE", "fr-FR"]`. Empty list fails the task with a clear validation message. |
| `outputDirectory` | `DirectoryProperty` | `$buildDir/ai-nemo` | Where the translated bundles are written. The convention is installed by the plugin. |
| `provider` | `Property<String>` | `"noop"` | One of `noop`, `nllb`, `opus`, `openai`, `anthropic`, `ollama`. See [docs/providers.md](providers.md). |
| `format` | `Property<String>` | inferred | Bundle format id. `null` = inferred from `sourceFile`'s extension (`.properties` → `java-properties`, `.po` → `gettext-po`, `.json` → `i18next-json`, `.xliff`/`.xlf` → `xliff`). Set explicitly for non-standard extensions. |
| `providerExecutable` | `Property<String>` | `"nemo"` | Path to the `nemo` console script. Override for venv installations or CI fixtures. The plugin spawns `<providerExecutable> daemon`. |
| `usageLogPath` | `RegularFileProperty` | daemon default (`~/.ainemo/usage.jsonl`) | JSONL path the daemon appends per-call usage records to. |
| `tmPath` | `RegularFileProperty` | daemon default (`./.ainemo/tm.sqlite`) | Translation memory database. |

`provider` defaults to `noop` so applying the plugin without
configuration produces a runnable build that exercises the
pipeline without touching any real model — useful for smoke-testing
the wiring before adding real credentials.

### Task: `translateBundles`

The plugin registers one task. Group `ai-nemo`. Inputs / outputs
are declared so Gradle's incremental build cache picks up
unchanged source bundles correctly. The translation memory provides
a second caching layer at the segment level (per
[docs/translation-memory.md](translation-memory.md)).

---

## What the task does

On each run, `translateBundles`:

1. Validates `targetLanguages` is non-empty and `sourceFile`
   exists. Misconfiguration fails the task before spawning the
   daemon.
2. Spawns `$providerExecutable daemon` once and pipes JSON
   over stdin/stdout (newline-delimited, semver-pinned envelope).
3. Pings the daemon for a health check before issuing real work
   — if the executable is wrong, you get a clear "daemon won't
   ping" failure rather than a confusing translate error later.
4. Issues one `translate_file` request with all configured target
   languages. The Python pipeline handles parsing, TM lookup,
   provider routing, validation, and serialization for the whole
   batch in one daemon-process lifetime — model load + SDK init +
   `sentence-transformers` boot amortizes across all targets.
5. Writes per-target output files keyed by language under
   `outputDirectory`.
6. Reports a one-line lifecycle summary plus per-target paths to
   the build log, then closes the daemon (10-second graceful
   shutdown, force-kill thereafter).

Validation errors from the pipeline (e.g. dropped placeholders)
fail the task with a count and point at the JSON usage log for
details.

---

## IPC contract

The wire is newline-delimited UTF-8 JSON, semver-pinned via the
envelope's `v` key. Cycle 2 ships version `"1"`; a mismatch on
either side is a hard error rather than a guess.

### Request

```json
{
  "v": "1",
  "id": "<call-id>",
  "op": "<operation>",
  "params": { ... }
}
```

### Response (ok)

```json
{
  "v": "1",
  "id": "<call-id>",
  "ok": true,
  "result": { ... }
}
```

### Response (error)

```json
{
  "v": "1",
  "id": "<call-id>",
  "ok": false,
  "error": {
    "code": "<stable-code>",
    "message": "<human-readable>"
  }
}
```

The `id` field correlates request to response. The cycle-2
`DaemonClient` asserts the response id matches the request id and
treats a mismatch as a poisoned connection (cycle-2 P2 fix). The
Gradle plugin issues requests sequentially in cycle 2; future
multiplexing reuses the same id mechanism.

### Operations

| Op | Purpose | Result keys |
|---|---|---|
| `ping` | Health check before issuing real work. | `pong: true` |
| `translate` | Single-segment translation. The Gradle task does **not** use this in cycle 2; reserved for cycle-3+ per-segment integrations. | `target_text`, `provider`, `model`, `input_tokens`, `output_tokens`, `latency_ms`, `cost_usd` |
| `translate_file` | Whole-bundle translation (the Gradle task's hot path). | `target_lang_paths` (lang → file), `tm_hit_count`, `provider_call_count`, `error_count`, `warning_count` |

### Error codes

Stable strings — pattern-match on `error.code` rather than
message text.

| Code | When |
|---|---|
| `invalid-json` | Request line wasn't parseable as JSON. |
| `invalid-envelope` | Request parsed but wasn't a JSON object, or `op` was missing/non-string. |
| `version-mismatch` | Request `v` ≠ daemon's protocol version. |
| `unknown-op` | Op name isn't in the daemon's handler table. |
| `invalid-params` | Op-specific param validation failed (missing required field, wrong type, nonexistent source path, empty target_langs, unsupported source extension via SystemExit). |
| `provider-failure` | Selected provider returned `False` from `supports()` for the pair, or no routing rule matched and the default isn't registered. |
| `internal` | Anything else — surfaces as an envelope rather than a Python traceback on stdout, but the message is `<ExceptionClass>: <str(exc)>`. |

The serve loop survives every error envelope — one bad request
never takes down the daemon (cycle-2 invariant, explicitly tested).

### Wire framing

- **UTF-8 only.** Both sides reconfigure stdin/stdout to UTF-8
  with `newline=""` (cycle-2 P1 fix); CRLF translation on Windows
  would otherwise corrupt framing for any payload whose JSON
  contains a literal `\r`.
- **Stderr is reserved** for human-readable diagnostics that
  surface in the Gradle build log. Never write JSON to stderr.

---

## Building this module

> **Bootstrap note (cycle-3 cooldown).** The repo currently ships
> the plugin source but not a Gradle wrapper. On first build,
> generate one with a system Gradle 8.5+ install:
>
> ```bash
> cd gradle-plugin
> gradle wrapper --gradle-version 8.10
> ./gradlew :gradle-plugin:check
> ```
>
> Cycle-3 cooldown commits the wrapper alongside a CI workflow
> that runs `:gradle-plugin:check` on JDK 17 + 21. See
> `specs/retros/cycle-2.md` § "Carryover into cooldown" #3.

```bash
./gradlew build              # compile + unit tests (DaemonClientTest)
./gradlew functionalTest     # TestKit (spawns Gradle daemons + nemo)
./gradlew check              # both
./gradlew publishPlugins --dry-run  # validate publication metadata
```

`functionalTest` requires `nemo` on PATH. Set up the venv first:

```bash
# from repo root
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
which nemo  # confirm before running TestKit
```

---

## Publishing to the Plugin Portal

Per cycle-2 pitch open-question 6: publish is a deliberate human
gate, not automated by CI. Set portal credentials in
`~/.gradle/gradle.properties`:

```properties
gradle.publish.key=<api-key>
gradle.publish.secret=<api-secret>
```

Or use the `ORG_GRADLE_PROJECT_gradle.publish.key` /
`ORG_GRADLE_PROJECT_gradle.publish.secret` env vars on CI.
Then:

```bash
./gradlew publishPlugins
```

CI verification stops at `publishPlugins --dry-run`, which
validates publication metadata without uploading.

---

## Troubleshooting

### `daemon won't ping` / `Cannot run program "nemo"`

The plugin can't find the `nemo` console script. Check:

1. `which nemo` finds an executable on the same shell that runs
   Gradle. If you `pip install -e .` into a venv, that venv must
   be active when invoking Gradle, or pass an absolute path:

   ```kotlin
   aiNemoTranslate {
       providerExecutable.set("/path/to/.venv/bin/nemo")
   }
   ```

2. The script actually launches:

   ```bash
   nemo --version    # or nemo --help
   ```

   If `pip install` finished but `nemo` isn't on PATH, the install
   probably went into a user-scheme location not on PATH; activate
   the venv or invoke `python -m ainemo.cli`.

### `OPENAI_API_KEY is not set` (or the Anthropic equivalent)

The cloud providers read credentials from env vars at first
`translate()` call. Pass them through to the Gradle invocation:

```bash
OPENAI_API_KEY="sk-..." ./gradlew translateBundles
```

In CI, set them as repository secrets and inject via the
workflow's `env:`. **Never** commit them to `build.gradle.kts`
or `~/.gradle/gradle.properties` (per AGENTS.md §
Translation-Domain Conventions: API keys via env vars only).

### `version-mismatch` from the daemon

The plugin and the `nemo` binary speak different protocol
versions. Either upgrade the plugin (newer wire) or downgrade
`nemo` (older wire) so both ends match. The protocol version is
pinned at `DaemonClient.PROTOCOL_VERSION` (Kotlin) and
`PROTOCOL_VERSION` in `src/ainemo/cli/daemon.py` (Python).

### Validation errors block the build

`translateBundles` fails with a count of error-severity violations
when validators (placeholder parity, ICU syntax, length budget,
forbidden terms) flag a translation. The JSON usage log records
the fingerprint of each failed segment. Inspect with:

```bash
nemo provider stats --usage-log .ainemo/usage.jsonl
nemo validate --source <bundle>_en_US.properties --target <bundle>_de_DE.properties --to-lang de-DE
```

### `Source bundle not found`

The task's `sourceFile` resolved to a non-existent path. Check
the relative path is correct from the project's working
directory and that the file actually exists at task-execution
time (Gradle's input snapshot uses the path you set; a missing
file isn't catchable until task action).

### `targetLanguages must contain at least one BCP-47 tag`

Empty `targetLanguages` is a misconfiguration, not a silent
no-op. Add at least one tag.

### Wrong JDK / `Unsupported class file major version`

The plugin requires JDK 17+ at build time. Check
`./gradlew --version`; if it reports a JDK below 17, configure a
toolchain in your root build script or set `JAVA_HOME` to a JDK
17+ install.

### Windows pipe deadlock or hang

Cycle 2 doesn't capture daemon stderr on a separate pump thread —
a chatty daemon could in principle fill the stderr pipe and block.
Tracked as a Medium-severity cooldown item (see
`specs/retros/cycle-2.md`); workaround is to redirect daemon
stderr to a file via the venv-launch shell:

```bash
nemo daemon 2>>nemo-daemon.log
```

---

## Cycle-2 limitations (cooldown candidates)

These are explicit and tracked in
`specs/retros/cycle-2.md` § "Carryover into cooldown":

- No Gradle wrapper checked in; no CI workflow for the plugin.
- `tmPath` and `usageLogPath` are typed `@InputFile` but the TM is
  daemon-created and the log is an output — first-run / incremental
  semantics need real `./gradlew check` exercise to confirm.
- No payload-size ceiling on the daemon's stdin reader.
- Concurrency: the daemon is single-threaded; the Kotlin client's
  `AtomicLong` correlation-id counter is forward-looking.
- Cross-language nullable drift: `DaemonClient` uses `as String`
  casts on fields the daemon could in principle drop.

The plugin is production-ready for the happy-path cycle-2 use
case (one bundle, N target langs, one of the six providers) on
macOS / Linux + JDK 17+. Cooldown closes the operational gaps
before cycle 3.
