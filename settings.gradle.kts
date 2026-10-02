// Gradle root for Cohortex's Java services (ADR-011).
// Modules are added by their work packages:
//   WP-02/WP-04: include("services:fleet-api")
//   WP-13:       include("services:stream-ingest")

plugins {
  // Downloads the JDK version requested by each module's toolchain (Temurin 25, docs/versions.md).
  id("org.gradle.toolchains.foojay-resolver-convention") version "1.0.0"
}

rootProject.name = "cohortex"
