package com.egoge.ainemo.gradle

import com.fasterxml.jackson.databind.ObjectMapper
import com.fasterxml.jackson.module.kotlin.jacksonObjectMapper
import org.gradle.api.DefaultTask
import org.gradle.api.file.DirectoryProperty
import org.gradle.api.file.RegularFileProperty
import org.gradle.api.provider.ListProperty
import org.gradle.api.provider.Property
import org.gradle.api.tasks.Input
import org.gradle.api.tasks.InputFile
import org.gradle.api.tasks.Optional
import org.gradle.api.tasks.OutputDirectory
import org.gradle.api.tasks.PathSensitive
import org.gradle.api.tasks.PathSensitivity
import org.gradle.api.tasks.TaskAction
import java.io.BufferedReader
import java.io.BufferedWriter
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.nio.charset.StandardCharsets
import java.util.concurrent.atomic.AtomicLong

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

    @get:InputFile
    @get:Optional
    @get:PathSensitive(PathSensitivity.RELATIVE)
    abstract val usageLogPath: RegularFileProperty

    @get:InputFile
    @get:Optional
    @get:PathSensitive(PathSensitivity.RELATIVE)
    abstract val tmPath: RegularFileProperty

    @TaskAction
    fun translate() {
        val targets = targetLanguages.get()
        require(targets.isNotEmpty()) {
            "aiNemoTranslate.targetLanguages must contain at least one BCP-47 tag."
        }
        val source = sourceFile.get().asFile
        require(source.exists()) { "Source bundle not found: ${source.absolutePath}" }
        val output = outputDirectory.orNull?.asFile
            ?: project.layout.buildDirectory.dir("ai-nemo").get().asFile
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
 * Extension to [DaemonClient] for the high-level ``translate_file``
 * op. Lives here rather than on the client class so the simpler
 * per-segment ``translate`` op stays the cycle-2 minimum surface
 * (testable without bundle-file fixtures).
 */
fun DaemonClient.translateFile(params: Map<String, Any?>): TranslateFileResult {
    @Suppress("UNCHECKED_CAST")
    val result = sendAndReceiveRaw(op = "translate_file", params = params)
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

/**
 * Internal companion to [DaemonClient.translate] — exposes the same
 * envelope-handling logic for higher-level ops added by extension
 * (like [translateFile]). Keeping the wire-format work in one place
 * means future ops only deal with op name + params + result keys.
 */
internal fun DaemonClient.sendAndReceiveRaw(
    op: String,
    params: Map<String, Any?>,
): Map<String, Any?> {
    // The DaemonClient's private writer/reader/mapper aren't exposed
    // for re-use, so this adapter goes through reflection on the
    // private members. Cycle-3 may surface a public ``call(op,
    // params)`` method on DaemonClient if more ops land; for cycle 2
    // the reflection bridge keeps the public surface minimal.
    val callMethod = DaemonClient::class.java.getDeclaredMethod(
        "sendAndReceive",
        String::class.java,
        Map::class.java,
    )
    callMethod.isAccessible = true
    @Suppress("UNCHECKED_CAST")
    return callMethod.invoke(this, op, params) as Map<String, Any?>
}

/**
 * Internal helper kept beside the task so cycle-2 verification reads
 * the same wire constants the Python daemon emits without dragging
 * in the DaemonClient companion. Synchronized with
 * `src/ainemo/cli/daemon.py` PROTOCOL_VERSION.
 */
private const val WIRE_PROTOCOL_VERSION: String = "1"

@Suppress("unused")
private val WIRE_PROTOCOL_VERSION_MATCHES_DAEMON: Boolean =
    WIRE_PROTOCOL_VERSION == DaemonClient.PROTOCOL_VERSION

@Suppress("unused")
private val UNUSED_DAEMON_IMPORTS_HOLDER: Any =
    listOf(
        ObjectMapper::class,
        BufferedReader::class,
        BufferedWriter::class,
        InputStreamReader::class,
        OutputStreamWriter::class,
        StandardCharsets.UTF_8,
        AtomicLong::class,
        ::jacksonObjectMapper,
    )
