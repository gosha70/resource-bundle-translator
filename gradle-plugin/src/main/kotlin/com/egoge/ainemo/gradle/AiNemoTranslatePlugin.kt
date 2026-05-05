package com.egoge.ainemo.gradle

import org.gradle.api.Plugin
import org.gradle.api.Project
import org.gradle.kotlin.dsl.register

/**
 * Cycle-2 entry point. Per the pitch: *"the plugin is a thin
 * façade. Translation logic stays in the Python core; the plugin
 * shells out via JSON-over-stdio."*
 *
 * Wires:
 *  - `aiNemoTranslate` extension (configured DSL surface)
 *  - `translateBundles` task (the actual work)
 *
 * Apply with:
 * ```kotlin
 * plugins { id("com.egoge.ai.nemo.translate") version "0.1.0" }
 * aiNemoTranslate {
 *     sourceFile = file("src/main/resources/messages_en_US.properties")
 *     targetLanguages = listOf("de-DE", "fr-FR", "es-ES")
 *     provider = "noop" // or nllb / opus / openai / anthropic / ollama
 * }
 * ```
 */
class AiNemoTranslatePlugin : Plugin<Project> {
    override fun apply(project: Project) {
        val extension =
            project.extensions.create(
                EXTENSION_NAME,
                AiNemoTranslateExtension::class.java,
            )
        // P2 fix (PR #7 review): the extension docs promise that
        // ``outputDirectory`` defaults to ``$buildDir/ai-nemo`` when
        // unset. Setting that default needs the project's layout
        // (which the @Inject constructor doesn't see), so the
        // convention is wired here in apply(). Without this, Gradle's
        // required-property validation rejects the task before its
        // @TaskAction body — its own runtime fallback is unreachable.
        extension.outputDirectory.convention(project.layout.buildDirectory.dir("ai-nemo"))

        // Use the typed Kotlin DSL ``register<T>`` extension instead
        // of ``register(name, Class, Action)``. The three-arg form
        // collides with the ``register(name, Class, vararg Any)``
        // overload at the call site (Kotlin 2.x can't tell whether
        // the trailing lambda is a configure block or a vararg).
        project.tasks.register<TranslateBundlesTask>(TASK_NAME) {
            group = "ai-nemo"
            description =
                "Translate one resource bundle into N target languages via the AI-NEMO " +
                    "Python daemon. Reproducible by default (provider temperature 0; TM cache)."
            // Wire the extension's properties through to the task.
            sourceFile.set(extension.sourceFile)
            targetLanguages.set(extension.targetLanguages)
            sourceLanguage.set(extension.sourceLanguage)
            outputDirectory.set(extension.outputDirectory)
            provider.set(extension.provider)
            providerExecutable.set(extension.providerExecutable)
            usageLogPath.set(extension.usageLogPath)
            tmPath.set(extension.tmPath)
            format.set(extension.format)
        }
    }

    companion object {
        const val EXTENSION_NAME: String = "aiNemoTranslate"
        const val TASK_NAME: String = "translateBundles"
    }
}
