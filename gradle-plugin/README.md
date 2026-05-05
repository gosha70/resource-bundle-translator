# AI-NEMO Translate — Gradle plugin

Cycle-2 thin Gradle façade over the AI-NEMO Python daemon. Add the
plugin to a JVM-shaped build and have it translate one resource
bundle into N target languages at build time, with reproducible
output (provider temperature 0; segment-keyed translation memory).

## Coordinates

- Plugin id: `com.egoge.ai.nemo.translate`
- Maven group: `com.egoge.ai.nemo`
- Artifact: `translate-gradle-plugin`
- Min Gradle: 8.5  ·  Min JDK: 17

## Usage

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
    provider.set("openai")              // noop / nllb / opus / openai / anthropic / ollama
    outputDirectory.set(layout.buildDirectory.dir("ai-nemo"))
}
```

```bash
./gradlew translateBundles
```

The task spawns one `nemo daemon` subprocess per task run and issues a
single `translate_file` request — model load and SDK init amortize
across all configured target languages.

## Preconditions

- The `nemo` console-script must be on the build's PATH. Install via
  ``pip install ai-nemo`` (or ``pip install -e ".[dev]"`` against this
  repo). The plugin shells out to it via the `providerExecutable`
  property.
- API keys for managed providers come from the **build environment**
  — `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`. Never put them in
  `build.gradle.kts` or check them into git (per AGENTS.md §
  Translation-Domain Conventions).

## Building this module

The plugin is a **standalone Gradle build** with its own wrapper.
Cycle-2 cooldown bootstrapped the wrapper (Gradle 8.10) and pinned
the build invocations as below — note that all commands run from
within `gradle-plugin/` because the wrapper is here, not at the
repo root.

```bash
cd gradle-plugin
./gradlew build               # compile + unit tests (DaemonClientTest)
./gradlew functionalTest      # TestKit (spawns Gradle daemons + nemo)
./gradlew check               # both — main CI entry point
./gradlew publishPlugins --dry-run   # validate publication metadata
```

`functionalTest` and `DaemonClientTest` use JUnit 5 `Assumptions` to
skip cleanly when their preconditions are missing — `DaemonClientTest`
needs `python3` on PATH; `functionalTest` needs `nemo` on PATH (the
AI-NEMO console script). On a JDK-only CI runner they show as
**skipped** rather than failed; the rest of `check` still runs.

To run the full `check` locally:

```bash
# from repo root
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
which nemo                    # confirm before functionalTest
cd gradle-plugin && ./gradlew check
```

## Publishing to the Plugin Portal

Per cycle-2 pitch open-question 6: publish is a deliberate human
gate, not automated by CI. Set portal credentials in
`~/.gradle/gradle.properties`:

```properties
gradle.publish.key=<api-key>
gradle.publish.secret=<api-secret>
```

Then (from `gradle-plugin/`):

```bash
./gradlew publishPlugins
```

## Wire protocol with the daemon

Newline-delimited JSON, semver in the envelope (`"v": "1"`). See
`src/ainemo/cli/daemon.py` in this repo for the canonical schema.
The plugin's `DaemonClient` mirrors the protocol exactly; cycle-2
pins version 1 and surfaces a mismatch as a hard build failure.
