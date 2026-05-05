package com.egoge.ainemo.gradle

import org.gradle.api.file.DirectoryProperty
import org.gradle.api.file.RegularFileProperty
import org.gradle.api.model.ObjectFactory
import org.gradle.api.provider.ListProperty
import org.gradle.api.provider.Property
import javax.inject.Inject

/**
 * DSL surface for the AI-NEMO translate plugin.
 *
 * Every property is a Gradle [Property] so configuration is lazy
 * (deferred to task execution) and so the build cache can pick up
 * changes via input snapshotting.
 */
abstract class AiNemoTranslateExtension
    @Inject
    constructor(objects: ObjectFactory) {
        /** The bundle file to translate. Must exist at task execution time. */
        val sourceFile: RegularFileProperty = objects.fileProperty()

        /** BCP-47 source-language tag. Defaults to ``en-US``. */
        val sourceLanguage: Property<String> = objects.property(String::class.java).convention("en-US")

        /** BCP-47 target tags, e.g. ``["de-DE", "fr-FR", "ja-JP"]``. */
        val targetLanguages: ListProperty<String> = objects.listProperty(String::class.java)

        /**
         * Where the translated bundles are written. Defaults to
         * ``$buildDir/ai-nemo``; the daemon's serialize step writes
         * one file per target language using the adapter's locale-
         * suffix convention (e.g. ``messages_de_DE.properties``).
         */
        val outputDirectory: DirectoryProperty = objects.directoryProperty()

        /**
         * Provider id. One of ``noop``, ``nllb``, ``opus``, ``openai``,
         * ``anthropic``, ``ollama``. Defaults to ``noop`` so applying
         * the plugin without configuration produces a runnable build
         * that exercises the pipeline without touching any model.
         */
        val provider: Property<String> = objects.property(String::class.java).convention("noop")

        /**
         * Bundle format id. ``null`` = inferred from sourceFile's
         * extension (``.properties`` → java-properties, ``.po`` →
         * gettext-po, etc). Set explicitly for non-standard
         * extensions.
         */
        val format: Property<String> = objects.property(String::class.java)

        /**
         * Path to the ``nemo`` executable. Defaults to ``nemo`` (on
         * PATH); override for venv installations or CI fixtures.
         * The plugin spawns ``<providerExecutable> daemon`` and
         * exchanges newline-delimited JSON.
         */
        val providerExecutable: Property<String> =
            objects.property(String::class.java).convention("nemo")

        /** Override the usage-log JSONL path. Defaults to the daemon default. */
        val usageLogPath: RegularFileProperty = objects.fileProperty()

        /** Override the translation memory path. Defaults to the daemon default. */
        val tmPath: RegularFileProperty = objects.fileProperty()
    }
