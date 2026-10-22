package dev.cohortex.fleetapi.it;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.condition.EnabledIf;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.jdbc.Sql;

/**
 * Full application on a random port against a real Postgres (Flyway applies {@code
 * db/migrations}); the hand-computed dataset in {@code seed.sql} is loaded once per class. Skipped
 * when neither Docker nor an external test database is available.
 */
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@Tag("integration")
@EnabledIf("dev.cohortex.fleetapi.it.TestDatabase#available")
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@Sql(scripts = "/seed.sql", executionPhase = Sql.ExecutionPhase.BEFORE_TEST_CLASS)
public @interface IntegrationTest {}
