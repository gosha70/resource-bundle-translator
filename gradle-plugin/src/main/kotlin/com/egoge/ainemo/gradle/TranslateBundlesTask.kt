package com.egoge.ainemo.gradle

import org.gradle.api.DefaultTask
import org.gradle.api.file.DirectoryProperty
import org.gradle.api.file.RegularFileProperty
import org.gradle.api.provider.ListProperty
import org.gradle.api.provider.Property
import org.gradle.api.tasks.Input
import org.gradle.api.tasks.InputFile
import org.gradle.api.tasks.Internal
import org.gradle.api.tasks.LocalState
import org.gradle.api.tasks.Optional
import org.gradle.api.tasks.OutputDirectory
import org.gradle.api.tasks.PathSensitive
import org.gradle.api.tasks.PathSensitivity
import org.gradle.api.tasks.TaskAction

/**
 * Cycle-2 Gradle task that drives the AI-NEMO Python daemon's
 * ``translate_file`` op.
 *
 * The plugin spawns ``$providerExecutable daemon`` once per task run
 * and issues a single ``translate_file`` request with all configured
 * target languages. The Python pipeline handles parsing, TM lookup,
 * provider routing, validation, and serialization. The translated
 * files appear under [outputDirectory] keyed by target language.
 *
 * Inputs / outputs are declared so Gradle's incremental build cache
 * picks up unchanged source bundles correctly. The translation memory
 * (committed under ``./.ainemo/tm.sqlite`` by default — see
 * AGENTS.md § Translation-Domain Conventions) provides a second
 * caching layer at the segment level.
 */
abstract class TranslateBundlesTask : DefaultTask() {
    @get:InputFile
    @get:PathSensitive(PathSensitivity.RELATIVE)
    abstract val sourceFile: RegularFileProperty

    @get:Input
    abstract val sourceLanguage: Property<String>

    @get:Input
    abstract val targetLanguages: ListProperty<String>

    @get:OutputDirectory
    abstract val outputDirectory: DirectoryProperty

    @get:Input
    abstract val provider: Property<String>

    @get:Input
    @get:Optional
    abstract val format: Property<String>

    @get:Input
    abstract val providerExecutable: Property<String>

    /**
     * JSONL path the daemon appends per-call usage records to. The
     * file is an *output* of the task (the daemon writes; nothing
     * reads it during the build), so it is annotated [Internal] —
     * it is **not** part of the input fingerprint and the file's
     * presence or absence does not gate task validation. We do not
     * use [org.gradle.api.tasks.OutputFile] either: that would
     * couple Gradle's clean / cache-management to a log file we
     * want to persist across builds for cycle-2 ``nemo provider
     * stats`` aggregation.
     */
    // @Internal (not @OutputFile): persists across `./gradlew clean`
    // for cross-build `nemo provider stats` aggregation.
    @get:Internal
    abstract val usageLogPath: RegularFileProperty

    /**
     * Translation-memory SQLite path. Created by the daemon on
     * first run, read+written on every subsequent run.
     *
     * - Not [InputFile]: the file does not need to exist before the
     *   task runs (Gradle would refuse to schedule the task), and
     *   every successful run mutates it (busting the input cache for
     *   every other consumer of the TM file).
     * - Not [OutputFile]: the TM is persistent across builds; we
     *   don't want ``./gradlew clean`` to delete it.
     *
     * Per AGENTS.md § Translation-Domain Conventions, the default
     * lives at ``./.ainemo/tm.sqlite`` and is opt-in for git
     * tracking.
     */
    // @LocalState (not @InputFile/@OutputFile): task-managed state
    // Gradle leaves alone — survives `./gradlew clean`, doesn't
    // gate task scheduling on existence, doesn't bust the cache.
    @get:LocalState
    abstract val tmPath: RegularFileProperty

    @TaskAction
    fun translate() {
        val targets = targetLanguages.get()
        require(targets.isNotEmpty()) {
            "aiNemoTranslate.targetLanguages must contain at least one BCP-47 tag."
        }
        val source = sourceFile.get().asFile
        require(source.exists()) { "Source bundle not found: ${source.absolutePath}" }
        // The extension installs a ``$buildDir/ai-nemo`` convention on
        // outputDirectory in AiNemoTranslatePlugin.apply(); ``get()``
        // is safe here because Gradle's required-property validation
        // would have failed the task earlier if neither the
        // convention nor an explicit value were set.
        val output = outputDirectory.get().asFile
        output.mkdirs()

        val pluginLogger = GradleLoggerAdapter(logger)
        val daemonArgs = buildList {
            usageLogPath.orNull?.asFile?.let {
                add("--usage-log")
                add(it.absolutePath)
            }
        }

        DaemonClient.start(
            executable = providerExecutable.get(),
            logger = pluginLogger,
            extraArgs = daemonArgs,
        ).use { client ->
            // Sanity-check the daemon before issuing real work — if the
            // executable is wrong, fail fast with a clear "daemon won't
            // ping" message rather than a confusing translate failure.
            client.ping()

            val params = buildMap<String, Any?> {
                put("source_path", source.absolutePath)
                put("target_langs", targets)
                put("output_dir", output.absolutePath)
                put("source_lang", sourceLanguage.get())
                put("provider", provider.get())
                format.orNull?.let { put("format", it) }
                tmPath.orNull?.asFile?.absolutePath?.let { put("tm_path", it) }
            }
            val result = client.translateFile(params)

            logger.lifecycle(
                "AI-NEMO translated ${source.name}: " +
                    "tm hits=${result.tmHitCount}, provider calls=${result.providerCallCount}, " +
                    "errors=${result.errorCount}, warnings=${result.warningCount}",
            )
            for ((lang, path) in result.targetLangPaths) {
                logger.lifecycle("  -> $lang: $path")
            }
            if (result.errorCount > 0) {
                throw IllegalStateException(
                    "AI-NEMO translation finished with ${result.errorCount} validation errors; " +
                        "see the JSON log for details.",
                )
            }
        }
    }
}

/**
 * Bridge from the Gradle [org.gradle.api.logging.Logger] to the
 * lightweight [PluginLogger] interface the [DaemonClient] depends on.
 * Keeping the client decoupled from Gradle classes makes unit testing
 * the IPC much easier (no need to construct a real Gradle logger).
 */
class GradleLoggerAdapter(private val logger: org.gradle.api.logging.Logger) : PluginLogger {
    override fun info(message: String) = logger.info(message)

    override fun warn(message: String) = logger.warn(message)
}

/**
 * Result of a daemon ``translate_file`` op — the Kotlin mirror of
 * Python's :class:`ainemo.core.pipeline.PipelineFileResult`.
 */
data class TranslateFileResult(
    val targetLangPaths: Map<String, String>,
    val tmHitCount: Int,
    val providerCallCount: Int,
    val errorCount: Int,
    val warningCount: Int,
)

/**
 * Extension on [DaemonClient] for the high-level ``translate_file``
 * op. Lives here rather than on the client class so the simpler
 * per-segment ``translate`` op stays the cycle-2 minimum surface
 * (unit-testable without bundle-file fixtures).
 */
fun DaemonClient.translateFile(params: Map<String, Any?>): TranslateFileResult {
    val result = call(op = "translate_file", params = params)
    @Suppress("UNCHECKED_CAST")
    val targetLangPaths = result["target_lang_paths"] as Map<String, String>
    return TranslateFileResult(
        targetLangPaths = targetLangPaths,
        tmHitCount = (result["tm_hit_count"] as Number).toInt(),
        providerCallCount = (result["provider_call_count"] as Number).toInt(),
        errorCount = (result["error_count"] as Number).toInt(),
        warningCount = (result["warning_count"] as Number).toInt(),
    )
}
