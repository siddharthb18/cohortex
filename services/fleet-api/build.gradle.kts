// C3 fleet-api: read-only REST API over the serving store (WP-04, ADR-011).
import org.springframework.boot.gradle.plugin.SpringBootPlugin

plugins {
  java
  // Versions come from the root build (declared there with `apply false`).
  id("org.springframework.boot")
  id("com.diffplug.spotless")
  id("net.ltgt.errorprone")
}

// JDK 25 by default (docs/versions.md); `-PjavaToolchain=21` builds on a JDK 21-only machine.
val javaToolchain: String =
  providers.gradleProperty("javaToolchain").getOrElse(libs.versions.java.get())

java { toolchain { languageVersion = JavaLanguageVersion.of(javaToolchain.toInt()) } }

dependencies {
  implementation(platform(SpringBootPlugin.BOM_COORDINATES))
  implementation("org.springframework.boot:spring-boot-starter-webmvc")
  implementation("org.springframework.boot:spring-boot-starter-jdbc")
  implementation("org.springframework.boot:spring-boot-starter-actuator")
  implementation("org.springframework.boot:spring-boot-starter-flyway")
  implementation(libs.springdoc.webmvc.ui)
  implementation(libs.commons.statistics.distribution)
  runtimeOnly("org.flywaydb:flyway-database-postgresql")
  runtimeOnly("org.postgresql:postgresql")

  errorprone(libs.errorprone.core)

  testImplementation(platform(SpringBootPlugin.BOM_COORDINATES))
  testImplementation(platform(libs.testcontainers.bom))
  testImplementation("org.springframework.boot:spring-boot-starter-test")
  testImplementation("org.springframework.boot:spring-boot-starter-webmvc-test")
  testImplementation("org.testcontainers:testcontainers-postgresql")
  testImplementation("org.testcontainers:testcontainers-junit-jupiter")
  testRuntimeOnly("org.junit.platform:junit-platform-launcher")
}

spotless {
  java {
    target("src/**/*.java")
    googleJavaFormat() // Spotless picks a version its API supports; pinning 1.37 broke it
  }
}

tasks.named<Jar>("jar") { enabled = false }

tasks.bootJar { archiveFileName = "fleet-api.jar" }

val repoRoot: String = rootProject.layout.projectDirectory.asFile.absolutePath

tasks.test {
  useJUnitPlatform {
    // `-PskipIntegration` runs only the pure unit tests.
    if (providers.gradleProperty("skipIntegration").isPresent) excludeTags("integration")
  }
  systemProperty("cohortex.repoRoot", repoRoot)
  // Test inputs that live outside this module.
  inputs.file(rootProject.layout.projectDirectory.file("contracts/fixtures/afr_ci_cases.json"))
  inputs.file(rootProject.layout.projectDirectory.file("contracts/openapi/fleet-api.yaml"))
  inputs.dir(rootProject.layout.projectDirectory.dir("db/migrations"))
  inputs.property(
    "externalTestDb",
    providers.environmentVariable("COHORTEX_FLEET_TEST_JDBC_URL").orElse(""),
  )
  testLogging { events("passed", "skipped", "failed") }
}

tasks.bootRun {
  // Flyway reads ../../db/migrations relative to this module (application.properties).
  workingDir = projectDir
}
