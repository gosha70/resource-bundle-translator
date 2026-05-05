// Standalone settings for the gradle-plugin module so it can be built
// independently from the rest of the AI-NEMO repo. Contributors who
// want a quick ``./gradlew :gradle-plugin:functionalTest`` run a
// composite-build root could be added later; for cycle 2 the module
// is its own project.

rootProject.name = "ai-nemo-gradle-plugin"

pluginManagement {
    repositories {
        gradlePluginPortal()
        mavenCentral()
    }
}
