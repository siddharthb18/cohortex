package dev.cohortex.fleetapi.afr;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import dev.cohortex.fleetapi.RepoPaths;
import java.io.IOException;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/**
 * FR-ANA-1: the Java exact Poisson interval agrees with the Python (SciPy) reference on all 1,000
 * cases of {@code contracts/fixtures/afr_ci_cases.json} to 1e-9 relative. Pure unit test.
 */
class AfrMathTest {

  private static final double REL_TOL = 1e-9;

  @Test
  void agreesWithScipyFixtureOnAllCases() throws IOException {
    String json = Files.readString(RepoPaths.resolve("contracts/fixtures/afr_ci_cases.json"));
    JsonNode root = JsonMapper.builder().build().readTree(json);
    assertThat(root.get("method").asString()).isEqualTo(AfrMath.METHOD_95);

    JsonNode cases = root.get("cases");
    assertThat(cases.size()).isEqualTo(1000);

    List<String> mismatches = new ArrayList<>();
    for (int i = 0; i < cases.size(); i++) {
      JsonNode c = cases.get(i);
      long failures = c.get("failures").asLong();
      long driveDays = c.get("drive_days").asLong();
      double confidence = c.get("confidence").asDouble();

      AfrEstimate got = AfrMath.estimate(failures, driveDays, confidence);

      check(mismatches, i, "afr_pct", c.get("afr_pct").asDouble(), got.afrPct());
      check(mismatches, i, "ci_low_pct", c.get("ci_low_pct").asDouble(), got.ciLowPct());
      check(mismatches, i, "ci_high_pct", c.get("ci_high_pct").asDouble(), got.ciHighPct());
    }
    assertThat(mismatches).as("cases outside 1e-9 relative").isEmpty();
  }

  private static void check(
      List<String> mismatches, int index, String field, double expected, double actual) {
    boolean ok =
        expected == 0.0
            ? actual == 0.0
            : Math.abs(actual - expected) <= REL_TOL * Math.abs(expected);
    if (!ok) {
      mismatches.add(
          "case " + index + " " + field + ": expected " + expected + " but was " + actual);
    }
  }

  @Test
  void afrUsesBackblazeFormula() {
    // 2 failures over 9,098 drive-days: 2 * 365 * 100 / 9098.
    assertThat(AfrMath.afrPct(2, 9098)).isEqualTo(73000.0 / 9098.0);
    assertThat(AfrMath.afrPct(0, 1000)).isZero();
  }

  @Test
  void zeroFailuresHasZeroLowerBoundAndPositiveUpperBound() {
    AfrEstimate e = AfrMath.estimate95(0, 365);
    assertThat(e.afrPct()).isZero();
    assertThat(e.ciLowPct()).isZero();
    // Upper count for k = 0 is -ln(0.025) = 3.6889; one drive-year => 368.89 %.
    assertThat(e.ciHighPct()).isCloseTo(-Math.log(0.025) * 100.0, within(1e-9));
  }

  @Test
  void intervalBracketsTheEstimate() {
    AfrEstimate e = AfrMath.estimate95(5, 1_956_328);
    assertThat(e.ciLowPct()).isLessThan(e.afrPct());
    assertThat(e.ciHighPct()).isGreaterThan(e.afrPct());
  }

  @Test
  void rejectsInvalidInputs() {
    assertThatThrownBy(() -> AfrMath.estimate95(1, 0)).isInstanceOf(IllegalArgumentException.class);
    assertThatThrownBy(() -> AfrMath.estimate95(-1, 10))
        .isInstanceOf(IllegalArgumentException.class);
    assertThatThrownBy(() -> AfrMath.estimate(1, 10, 1.0))
        .isInstanceOf(IllegalArgumentException.class);
  }

  private static org.assertj.core.data.Offset<Double> within(double v) {
    return org.assertj.core.data.Offset.offset(v);
  }
}
