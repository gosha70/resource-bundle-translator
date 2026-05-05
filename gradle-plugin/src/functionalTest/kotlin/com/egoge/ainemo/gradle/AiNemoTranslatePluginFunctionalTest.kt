package com.egoge.ainemo.gradle

import org.gradle.testkit.runner.GradleRunner
import org.gradle.testkit.runner.TaskOutcome
import org.junit.jupiter.api.Assumptions.assumeTrue
import org.junit.jupiter.api.BeforeAll
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * Cycle-2 scope 12: TestKit drives a real Gradle build that applies
 * the plugin and runs ``translateBundles`` against the Python daemon.
 *
 * **Precondition:** the ``nemo`` console-script must be on PATH (the
 * project's ``pip install -e ".[dev]"`` installs it). CI sets this up
 * via the Python toolchain; locally, ``source .venv/bin/activate``
 * before running ``./gradlew :gradle-plugin:functionalTest``.
 *
 * The test uses ``--provider noop`` so it doesn't hit any real model
 * — keeps the run fast and offline. The end-to-end IPC path
 * (Kotlin → process → Python pipeline → output files) still gets
 * exercised.
 */
class AiNemoTranslatePluginFunctionalTest {
    companion object {
        @JvmStatic
        @BeforeAll
        fun checkNemoAvailable() {
            // The functional test spawns a real Gradle build that
            // applies the plugin and runs ``translateBundles``,
            // which in turn spawns ``nemo daemon``. Without ``nemo``
            // on PATH the test would fail with a confusing
            // "Cannot run program" error. Skip cleanly instead so
            // JDK-only CI matrices and contributors without the
            // Python venv activated can still run ``./gradlew check``
            // for the rest of the plugin's tests.
            //
            // Override path with -Dainemo.executable in
            // build.gradle.kts; we honor the same property here.
            val executable = System.getProperty("ainemo.executable", "nemo")
            val nemoOnPath =
                try {
                    val process =
                        ProcessBuilder(executable, "--help")
                            .redirectErrorStream(true)
                            .start()
                    process.waitFor() == 0
                } catch (_: Exception) {
                    false
                }
            assumeTrue(
                nemoOnPath,
                "$executable not on PATH; skipping TestKit functional test. " +
                    "Install AI-NEMO (pip install -e .[dev]) and re-run.",
            )
        }
    }

    @field:TempDir
    lateinit var projectDir: File

    @Test
    fun `translateBundles emits one output per target language`() {
        // Arrange: a single-segment Java properties bundle.
        val resources = File(projectDir, "src/main/resources").apply { mkdirs() }
        File(resources, "messages_en_US.properties").writeText("greeting=Hello\n")

        File(projectDir, "settings.gradle.kts").writeText(
            """
            rootProject.name = "functional-test"
            """.trimIndent(),
        )
        File(projectDir, "build.gradle.kts").writeText(
            """
            plugins {
                id("com.egoge.ai.nemo.translate")
            }
            aiNemoTranslate {
                sourceFile.set(file("src/main/resources/messages_en_US.properties"))
                sourceLanguage.set("en-US")
                targetLanguages.set(listOf("de-DE", "fr-FR"))
                outputDirectory.set(layout.buildDirectory.dir("ainemo-out"))
                provider.set("noop")
                providerExecutable.set(System.getProperty("ainemo.executable", "nemo"))
            }
            """.trimIndent(),
        )

        // Act
        val result = GradleRunner.create()
            .withProjectDir(projectDir)
            .withPluginClasspath()
            .withArguments("translateBundles", "--info", "--stacktrace")
            .build()

        // Assert
        assertEquals(TaskOutcome.SUCCESS, result.task(":translateBundles")?.outcome)

        val outDir = File(projectDir, "build/ainemo-out")
        assertTrue(File(outDir, "messages_de_DE.properties").exists())
        assertTrue(File(outDir, "messages_fr_FR.properties").exists())
    }

    @Test
    fun `translateBundles fails clearly when targetLanguages empty`() {
        File(projectDir, "src/main/resources").mkdirs()
        File(projectDir, "src/main/resources/messages_en_US.properties").writeText("k=v\n")

        File(projectDir, "settings.gradle.kts").writeText(
            """rootProject.name = "functional-test-empty"""",
        )
        File(projectDir, "build.gradle.kts").writeText(
            """
            plugins {
                id("com.egoge.ai.nemo.translate")
            }
            aiNemoTranslate {
                sourceFile.set(file("src/main/resources/messages_en_US.properties"))
                targetLanguages.set(emptyList<String>())
                provider.set("noop")
                providerExecutable.set(System.getProperty("ainemo.executable", "nemo"))
            }
            """.trimIndent(),
        )

        val result = GradleRunner.create()
            .withProjectDir(projectDir)
            .withPluginClasspath()
            .withArguments("translateBundles", "--stacktrace")
            .buildAndFail()

        // Build failed (the require() in the task) and the message
        // mentions the misconfiguration.
        assertTrue(
            result.output.contains("targetLanguages must contain at least one"),
            "Expected a clear validation message; got:\n${result.output}",
        )
    }
}
