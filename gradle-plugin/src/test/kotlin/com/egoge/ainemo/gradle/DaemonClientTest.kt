package com.egoge.ainemo.gradle

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.junit.jupiter.api.io.TempDir
import java.io.File
import java.nio.file.Path

/**
 * Unit tests for [DaemonClient] using a tiny "echo" daemon
 * implemented as a Python script. Lives in [src/test] so it runs as
 * part of the cheap unit suite (no Gradle TestKit needed).
 *
 * Precondition for these tests: `python3` on PATH. The fake daemon
 * is a self-contained 30-line script that mimics the
 * `nemo daemon` wire protocol just enough to exercise the
 * [DaemonClient] code paths.
 */
class DaemonClientTest {
    @field:TempDir
    lateinit var tempDir: Path

    private fun writeFakeDaemon(behavior: String): String {
        val script = tempDir.resolve("fake_daemon.py").toFile()
        script.writeText(behavior)
        script.setExecutable(true)
        return script.absolutePath
    }

    private val noopLogger =
        object : PluginLogger {
            override fun info(message: String) {}

            override fun warn(message: String) {}
        }

    @Test
    fun `ping returns through ok envelope`() {
        val script =
            writeFakeDaemon(
                """
                #!/usr/bin/env python3
                import sys, json
                for line in sys.stdin:
                    req = json.loads(line)
                    sys.stdout.write(json.dumps({
                        "v": "1", "id": req["id"], "ok": True,
                        "result": {"pong": True}
                    }) + "\n")
                    sys.stdout.flush()
                """.trimIndent(),
            )
        DaemonClient.startRaw(listOf("python3", script), noopLogger).use { client ->
            client.ping() // doesn't throw
        }
    }

    @Test
    fun `translate parses provider result`() {
        val script =
            writeFakeDaemon(
                """
                #!/usr/bin/env python3
                import sys, json
                for line in sys.stdin:
                    req = json.loads(line)
                    sys.stdout.write(json.dumps({
                        "v": "1", "id": req["id"], "ok": True,
                        "result": {
                            "target_text": "Hallo",
                            "provider": "fake",
                            "model": "fake-1.0",
                            "input_tokens": 7,
                            "output_tokens": 3,
                            "latency_ms": 42,
                            "cost_usd": None,
                        }
                    }) + "\n")
                    sys.stdout.flush()
                """.trimIndent(),
            )
        DaemonClient.startRaw(listOf("python3", script), noopLogger).use { client ->
            val r = client.translate("fake", "k", "Hello", "en-US", "de-DE")
            assertEquals("Hallo", r.targetText)
            assertEquals("fake", r.provider)
            assertEquals(7, r.inputTokens)
            assertEquals(42L, r.latencyMs)
            assertNull(r.costUsd)
        }
    }

    @Test
    fun `error envelope surfaces as DaemonException`() {
        val script =
            writeFakeDaemon(
                """
                #!/usr/bin/env python3
                import sys, json
                for line in sys.stdin:
                    req = json.loads(line)
                    sys.stdout.write(json.dumps({
                        "v": "1", "id": req["id"], "ok": False,
                        "error": {"code": "boom", "message": "intentional"}
                    }) + "\n")
                    sys.stdout.flush()
                """.trimIndent(),
            )
        DaemonClient.startRaw(listOf("python3", script), noopLogger).use { client ->
            val ex = assertThrows<DaemonException> { client.ping() }
            assertTrue(ex.message!!.contains("boom"))
            assertTrue(ex.message!!.contains("intentional"))
        }
    }

    @Test
    fun `version mismatch surfaces as DaemonException`() {
        val script =
            writeFakeDaemon(
                """
                #!/usr/bin/env python3
                import sys, json
                for line in sys.stdin:
                    req = json.loads(line)
                    sys.stdout.write(json.dumps({
                        "v": "999", "id": req["id"], "ok": True,
                        "result": {"pong": True}
                    }) + "\n")
                    sys.stdout.flush()
                """.trimIndent(),
            )
        DaemonClient.startRaw(listOf("python3", script), noopLogger).use { client ->
            val ex = assertThrows<DaemonException> { client.ping() }
            assertTrue(ex.message!!.contains("protocol version"))
        }
    }

    @Test
    fun `request id increments per call`() {
        // Daemon echoes the id back inside the result.
        val script =
            writeFakeDaemon(
                """
                #!/usr/bin/env python3
                import sys, json
                for line in sys.stdin:
                    req = json.loads(line)
                    sys.stdout.write(json.dumps({
                        "v": "1", "id": req["id"], "ok": True,
                        "result": {
                            "target_text": req["id"],
                            "provider": "fake",
                            "model": "fake-1.0",
                            "input_tokens": None,
                            "output_tokens": None,
                            "latency_ms": 0,
                            "cost_usd": None,
                        }
                    }) + "\n")
                    sys.stdout.flush()
                """.trimIndent(),
            )
        DaemonClient.startRaw(listOf("python3", script), noopLogger).use { client ->
            val a = client.translate("fake", "k1", "Hi", "en-US", "de-DE")
            val b = client.translate("fake", "k2", "Hi", "en-US", "de-DE")
            assertEquals("1", a.targetText)
            assertEquals("2", b.targetText)
        }
    }

    // Suppresses an "unused" warning on the field — Gradle's
    // @TempDir annotation does the assignment via reflection.
    @Suppress("unused")
    private fun keepReferenceToFile() {
        File("/").exists()
    }
}
