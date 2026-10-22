package dev.cohortex.fleetapi;

import java.nio.file.Path;

/** Locates files in the monorepo (contracts, fixtures) from tests. */
public final class RepoPaths {

  private RepoPaths() {}

  /** The repo root: the {@code cohortex.repoRoot} system property set by Gradle, else ../.. */
  public static Path root() {
    String configured = System.getProperty("cohortex.repoRoot");
    if (configured != null && !configured.isBlank()) {
      return Path.of(configured);
    }
    return Path.of("..", "..").toAbsolutePath().normalize();
  }

  public static Path resolve(String relative) {
    return root().resolve(relative);
  }
}
