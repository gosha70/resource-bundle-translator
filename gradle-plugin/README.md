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

> **Bootstrap note:** the repo currently ships the plugin source but
> not a Gradle wrapper. On first build, generate one with a system
> Gradle 8.5+ install:
>
> ```bash
> cd gradle-plugin
> gradle wrapper --gradle-version 8.10
> ./gradlew :gradle-plugin:check
> ```
>
> Cycle-3 cooldown will commit the wrapper alongside a CI workflow
> that runs `:gradle-plugin:check` on JDK 17 + 21.

```bash
./gradlew :gradle-plugin:build              # compile + unit tests
./gradlew :gradle-plugin:functionalTest     # TestKit (spawns daemons)
./gradlew :gradle-plugin:publishPlugins --dry-run  # verify metadata
```

## Publishing to the Plugin Portal

Per cycle-2 pitch open-question 6: publish is a deliberate human
gate, not automated by CI. Set portal credentials in
`~/.gradle/gradle.properties`:

```properties
gradle.publish.key=<api-key>
gradle.publish.secret=<api-secret>
```

Then:

```bash
./gradlew :gradle-plugin:publishPlugins
```

## Wire protocol with the daemon

Newline-delimited JSON, semver in the envelope (`"v": "1"`). See
`src/ainemo/cli/daemon.py` in this repo for the canonical schema.
The plugin's `DaemonClient` mirrors the protocol exactly; cycle-2
pins version 1 and surfaces a mismatch as a hard build failure.
