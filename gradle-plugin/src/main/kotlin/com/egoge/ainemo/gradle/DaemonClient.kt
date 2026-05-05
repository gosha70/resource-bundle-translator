package com.egoge.ainemo.gradle

import com.fasterxml.jackson.databind.ObjectMapper
import com.fasterxml.jackson.module.kotlin.jacksonObjectMapper
import java.io.BufferedReader
import java.io.BufferedWriter
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.nio.charset.StandardCharsets
import java.util.concurrent.atomic.AtomicLong

/**
 * Thin Kotlin wrapper around the cycle-2 ``nemo daemon`` subprocess.
 *
 * Wire format mirrors `src/ainemo/cli/daemon.py`. Each request is one
 * line of JSON; each response is one line of JSON. The wire schema is
 * versioned (envelope key ``v``); we pin to ``"1"`` and surface a
 * mismatch as a hard error rather than guessing semantics.
 *
 * Usage:
 * ```kotlin
 * DaemonClient.start("nemo", logger).use { client ->
 *     client.ping()
 *     val r = client.translate(
 *         providerId = "openai",
 *         key = "greeting",
 *         sourceText = "Hello, {name}!",
 *         sourceLang = "en-US",
 *         targetLang = "de-DE",
 *     )
 *     // r.targetText, r.provider, r.model, r.cost, r.latencyMs
 * }
 * ```
 *
 * Cycle-2 is single-threaded — the Gradle task fires translate
 * requests sequentially per (segment × target lang). If a future
 * cycle wants concurrency on top of one daemon process, the wire's
 * ``id`` field is already the correlation handle.
 */
class DaemonClient
    private constructor(
        private val process: Process,
        private val logger: PluginLogger,
    ) : AutoCloseable {
        private val mapper: ObjectMapper = jacksonObjectMapper()
        private val writer: BufferedWriter =
            BufferedWriter(OutputStreamWriter(process.outputStream, StandardCharsets.UTF_8))
        private val reader: BufferedReader =
            BufferedReader(InputStreamReader(process.inputStream, StandardCharsets.UTF_8))
        private val nextId = AtomicLong(1)

        fun ping() {
            sendAndReceive(op = "ping", params = emptyMap())
        }

        fun translate(
            providerId: String,
            key: String,
            sourceText: String,
            sourceLang: String,
            targetLang: String,
        ): TranslateResult {
            val params =
                mapOf(
                    "key" to key,
                    "source_text" to sourceText,
                    "source_lang" to sourceLang,
                    "target_lang" to targetLang,
                    "provider" to providerId,
                )
            val result = sendAndReceive(op = "translate", params = params)
            return TranslateResult(
                targetText = result["target_text"] as String,
                provider = result["provider"] as String,
                model = result["model"] as String,
                inputTokens = (result["input_tokens"] as Number?)?.toInt(),
                outputTokens = (result["output_tokens"] as Number?)?.toInt(),
                latencyMs = (result["latency_ms"] as Number).toLong(),
                costUsd = (result["cost_usd"] as Number?)?.toDouble(),
            )
        }

        @Suppress("UNCHECKED_CAST")
        private fun sendAndReceive(
            op: String,
            params: Map<String, Any?>,
        ): Map<String, Any?> {
            val callId = nextId.getAndIncrement().toString()
            val request: Map<String, Any?> =
                mapOf(
                    "v" to PROTOCOL_VERSION,
                    "id" to callId,
                    "op" to op,
                    "params" to params,
                )
            writer.write(mapper.writeValueAsString(request))
            writer.write("\n")
            writer.flush()

            val responseLine =
                reader.readLine()
                    ?: throw DaemonException(
                        "AI-NEMO daemon closed stdout before responding to op=$op id=$callId",
                    )
            val response = mapper.readValue(responseLine, Map::class.java) as Map<String, Any?>

            val responseVersion = response["v"]
            if (responseVersion != PROTOCOL_VERSION) {
                throw DaemonException(
                    "Daemon responded with unexpected protocol version $responseVersion " +
                        "(expected $PROTOCOL_VERSION). Mismatched daemon binary?",
                )
            }
            if (response["ok"] == true) {
                return response["result"] as Map<String, Any?>
            }
            val error = response["error"] as Map<String, Any?>
            throw DaemonException(
                "AI-NEMO daemon op=$op rejected with code=${error["code"]} " +
                    "message=${error["message"]}",
            )
        }

        override fun close() {
            try {
                writer.close()
            } catch (_: Exception) {
                // The daemon may already have exited cleanly via stdin EOF;
                // a follow-up close error is uninteresting.
            }
            // Wait briefly for graceful exit; force-kill if it hangs so a
            // misbehaving daemon doesn't block the build forever.
            val exitedCleanly = process.waitFor(GRACEFUL_EXIT_SECONDS, java.util.concurrent.TimeUnit.SECONDS)
            if (!exitedCleanly) {
                logger.warn(
                    "AI-NEMO daemon did not exit within ${GRACEFUL_EXIT_SECONDS}s; killing.",
                )
                process.destroyForcibly()
            }
        }

        companion object {
            const val PROTOCOL_VERSION: String = "1"
            const val GRACEFUL_EXIT_SECONDS: Long = 10

            /**
             * Spawn ``$executable daemon`` and return a connected
             * client. The caller owns the lifecycle and must call
             * [close] (or use Kotlin's ``use { ... }``) so the
             * subprocess is reaped.
             */
            fun start(
                executable: String,
                logger: PluginLogger,
                extraArgs: List<String> = emptyList(),
            ): DaemonClient {
                val command = mutableListOf(executable, "daemon")
                command.addAll(extraArgs)
                val builder =
                    ProcessBuilder(command)
                        .redirectError(ProcessBuilder.Redirect.INHERIT)
                val process = builder.start()
                return DaemonClient(process, logger)
            }
        }
    }

/** One translation outcome — the Kotlin mirror of Python's `ProviderResult`. */
data class TranslateResult(
    val targetText: String,
    val provider: String,
    val model: String,
    val inputTokens: Int?,
    val outputTokens: Int?,
    val latencyMs: Long,
    val costUsd: Double?,
)

/** Surfaces cleanly to Gradle as a build failure. */
class DaemonException(message: String) : RuntimeException(message)

/**
 * Tiny abstraction over the Gradle logger so the daemon client can
 * be unit-tested without bringing in `org.gradle.api.logging.Logger`.
 */
interface PluginLogger {
    fun info(message: String)

    fun warn(message: String)
}
