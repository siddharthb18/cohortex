package dev.cohortex.fleetapi.it;

import org.springframework.test.context.DynamicPropertyRegistry;
import org.testcontainers.DockerClientFactory;
import org.testcontainers.postgresql.PostgreSQLContainer;
import org.testcontainers.utility.DockerImageName;

/**
 * The Postgres + pgvector database for integration tests.
 *
 * <p>By default a Testcontainers {@code pgvector/pgvector:0.8.7-pg18} container (docs/versions.md)
 * is started once per test JVM. Where Docker is unavailable, set {@code
 * COHORTEX_FLEET_TEST_JDBC_URL} (plus {@code COHORTEX_FLEET_TEST_DB_USER} and {@code
 * COHORTEX_FLEET_TEST_DB_PASSWORD}) to an empty database with the pgvector extension available.
 * Flyway applies {@code db/migrations} from the repo in both cases.
 */
public final class TestDatabase {

  static final String IMAGE = "pgvector/pgvector:0.8.7-pg18";
  private static final String EXTERNAL_URL_ENV = "COHORTEX_FLEET_TEST_JDBC_URL";

  private static PostgreSQLContainer container;

  private TestDatabase() {}

  /** JUnit {@code @EnabledIf} condition: an external database is configured or Docker works. */
  public static boolean available() {
    if (externalUrl() != null) {
      return true;
    }
    try {
      return DockerClientFactory.instance().isDockerAvailable();
    } catch (RuntimeException e) {
      return false;
    }
  }

  static void register(DynamicPropertyRegistry registry) {
    String url = externalUrl();
    if (url != null) {
      registry.add("spring.datasource.url", () -> url);
      registry.add(
          "spring.datasource.username", () -> env("COHORTEX_FLEET_TEST_DB_USER", "cohortex"));
      registry.add("spring.datasource.password", () -> env("COHORTEX_FLEET_TEST_DB_PASSWORD", ""));
      return;
    }
    PostgreSQLContainer db = startContainer();
    registry.add("spring.datasource.url", db::getJdbcUrl);
    registry.add("spring.datasource.username", db::getUsername);
    registry.add("spring.datasource.password", db::getPassword);
  }

  private static synchronized PostgreSQLContainer startContainer() {
    if (container == null) {
      PostgreSQLContainer db =
          new PostgreSQLContainer(
              DockerImageName.parse(IMAGE).asCompatibleSubstituteFor("postgres"));
      db.start();
      container = db;
    }
    return container;
  }

  private static String externalUrl() {
    String url = System.getenv(EXTERNAL_URL_ENV);
    return url == null || url.isBlank() ? null : url;
  }

  private static String env(String name, String fallback) {
    String value = System.getenv(name);
    return value == null ? fallback : value;
  }
}
