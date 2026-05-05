package com.egoge.ainemo.gradle

import org.gradle.api.Plugin
import org.gradle.api.Project

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

        project.tasks.register(TASK_NAME, TranslateBundlesTask::class.java) { task ->
            task.group = "ai-nemo"
            task.description =
                "Translate one resource bundle into N target languages via the AI-NEMO " +
                    "Python daemon. Reproducible by default (provider temperature 0; TM cache)."
            // Wire the extension's properties through to the task.
            task.sourceFile.set(extension.sourceFile)
            task.targetLanguages.set(extension.targetLanguages)
            task.sourceLanguage.set(extension.sourceLanguage)
            task.outputDirectory.set(extension.outputDirectory)
            task.provider.set(extension.provider)
            task.providerExecutable.set(extension.providerExecutable)
            task.usageLogPath.set(extension.usageLogPath)
            task.tmPath.set(extension.tmPath)
            task.format.set(extension.format)
        }
    }

    companion object {
        const val EXTENSION_NAME: String = "aiNemoTranslate"
        const val TASK_NAME: String = "translateBundles"
    }
}
