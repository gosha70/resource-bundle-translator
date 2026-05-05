// AI-NEMO Gradle plugin — cycle-2 scope 10.
//
// Per AGENTS.md § Distribution namespace and the cycle-2 pitch
// open-question 1 resolution:
//   - Maven group:    com.egoge.ai.nemo
//   - Artifact:       translate-gradle-plugin
//   - Plugin id:      com.egoge.ai.nemo.translate
//   - Display name:   AI-NEMO Translate
//
// The plugin is a thin façade over the Python daemon (cycle-2
// scope 9). All translation logic stays in the Python core; the
// plugin shells out to ``nemo daemon`` and exchanges newline-
// delimited JSON. Per the pitch:
//   "The plugin is a thin façade. Translation logic stays in the
//    Python core; the plugin shells out via JSON-over-stdio (or
//    gRPC if benchmark warrants)."
//
// Build:
//   ./gradlew :gradle-plugin:build
// Functional tests (TestKit):
//   ./gradlew :gradle-plugin:functionalTest
// Plugin Portal dry-run publish:
//   ./gradlew :gradle-plugin:publishPlugins --dry-run

plugins {
    `kotlin-dsl`
    `java-gradle-plugin`
    id("com.gradle.plugin-publish") version "1.2.1"
    `maven-publish`
}

group = "com.egoge.ai.nemo"
version = "0.1.0"

repositories {
    mavenCentral()
    gradlePluginPortal()
}

dependencies {
    implementation(gradleApi())
    // Lightweight, dependency-free JSON parser. Cycle-2 plugin's IPC
    // payload is small (one envelope per segment); a 200KB reader/
    // writer is fine and keeps the plugin classpath narrow.
    // Switch to a more featureful parser only if benchmarks demand it.
    implementation("com.fasterxml.jackson.module:jackson-module-kotlin:2.18.2")

    testImplementation(kotlin("test"))
    testImplementation("org.jetbrains.kotlin:kotlin-test-junit5:2.1.0")
    testImplementation("org.junit.jupiter:junit-jupiter:5.11.4")
}

// ---------------------------------------------------------------------------
// Source-set: functionalTest (TestKit driver)
// ---------------------------------------------------------------------------
//
// TestKit needs its own source set so functional tests don't leak into
// the unit-test classpath and so CI can run the cheap unit tests
// without spawning Gradle daemons.

sourceSets {
    val functionalTest by creating {
        kotlin.srcDir("src/functionalTest/kotlin")
        compileClasspath += sourceSets.main.get().output + configurations.testRuntimeClasspath.get()
        runtimeClasspath += output + compileClasspath
    }
}

val functionalTestImplementation: Configuration =
    configurations["functionalTestImplementation"].apply {
        extendsFrom(configurations["testImplementation"])
    }

dependencies {
    functionalTestImplementation(gradleTestKit())
    functionalTestImplementation("org.jetbrains.kotlin:kotlin-test-junit5:2.1.0")
    functionalTestImplementation("org.junit.jupiter:junit-jupiter:5.11.4")
}

val functionalTest by tasks.registering(Test::class) {
    description = "Runs the Gradle TestKit functional tests (spawns real Gradle daemons)."
    group = "verification"
    testClassesDirs = sourceSets["functionalTest"].output.classesDirs
    classpath = sourceSets["functionalTest"].runtimeClasspath
    useJUnitPlatform()
}

tasks.named("check") { dependsOn(functionalTest) }

// ---------------------------------------------------------------------------
// Plugin descriptor
// ---------------------------------------------------------------------------

gradlePlugin {
    website.set("https://github.com/gosha70/resource-bundle-translator")
    vcsUrl.set("https://github.com/gosha70/resource-bundle-translator")
    plugins {
        create("ainemoTranslate") {
            id = "com.egoge.ai.nemo.translate"
            implementationClass = "com.egoge.ainemo.gradle.AiNemoTranslatePlugin"
            displayName = "AI-NEMO Translate"
            description =
                "Translate resource-bundle files (Java properties, i18next JSON, gettext PO, " +
                    "XLIFF) at build time via the AI-NEMO Python daemon. Library-first, " +
                    "local-first; no SaaS, no telemetry."
            tags.set(listOf("i18n", "translation", "localization", "resource-bundle", "ai-nemo"))
        }
    }
}

// ---------------------------------------------------------------------------
// Java/Kotlin toolchain
// ---------------------------------------------------------------------------

java {
    toolchain {
        languageVersion.set(JavaLanguageVersion.of(17))
    }
}

kotlin {
    jvmToolchain(17)
}

// ---------------------------------------------------------------------------
// Plugin Portal publishing — cycle-2 scope 13
// ---------------------------------------------------------------------------
//
// Per cycle-2 pitch open-question 6: actual publish is a deliberate
// human gate. CI verifies up to ``./gradlew :gradle-plugin:publishPlugins
// --dry-run`` (which validates the publication metadata without
// uploading). The user runs the real publish at cycle close with
// portal credentials from ``~/.gradle/gradle.properties``:
//
//     gradle.publish.key=<api-key>
//     gradle.publish.secret=<api-secret>
//
// or via ``ORG_GRADLE_PROJECT_gradle.publish.key`` /
// ``ORG_GRADLE_PROJECT_gradle.publish.secret`` env vars on CI.
//
// The ``com.gradle.plugin-publish`` plugin (declared at the top of
// this build script) wires the ``publishPlugins`` task automatically;
// the gradlePlugin {} block above carries the publication metadata.
