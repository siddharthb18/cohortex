package dev.cohortex.fleetapi.it;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

import dev.cohortex.fleetapi.afr.AfrEstimate;
import dev.cohortex.fleetapi.afr.AfrMath;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;

/**
 * FR-API-1/2/3/5/6/8 truth against the hand-computed dataset in {@code seed.sql}, plus RFC 9457
 * problem-details shapes and health probes (FR-OPS-4).
 */
@IntegrationTest
class FleetApiIT extends ApiTestBase {

  private static final double TOL = 1e-9;

  // ------------------------------------------------------------------ FR-API-1 models

  @Test
  void modelsListsEveryModelWithLatestDayDriveCount() throws Exception {
    Reply r = get("/v1/models");
    assertThat(r.status()).isEqualTo(200);
    JsonNode body = r.body();
    assertThat(body.get("total").asLong()).isEqualTo(4);
    assertThat(body.get("page").asInt()).isZero();
    assertThat(body.get("size").asInt()).isEqualTo(100);

    JsonNode items = body.get("items");
    assertThat(texts(items, "model")).containsExactly("MA1", "MODEL_A", "MODEL_B", "MODEL_C");
    JsonNode a = items.get(1);
    assertThat(a.get("id").asInt()).isEqualTo(1);
    assertThat(a.get("source").asString()).isEqualTo("backblaze");
    assertThat(a.get("media").asString()).isEqualTo("hdd");
    assertThat(a.get("capacity_bytes").asLong()).isEqualTo(12000138625024L);
    // drive_count on MODEL_A's latest day (2026-06-30) is 98, not the usual 100.
    assertThat(a.get("drive_count").asLong()).isEqualTo(98);
    assertThat(items.get(0).get("capacity_bytes").isNull()).isTrue();
    assertThat(items.get(0).get("drive_count").asLong()).isEqualTo(50);
  }

  @Test
  void modelsFilterBySourceAndMediaAndPage() throws Exception {
    JsonNode bb = get("/v1/models?source=backblaze").body();
    assertThat(texts(bb.get("items"), "model")).containsExactly("MODEL_A", "MODEL_B", "MODEL_C");
    assertThat(longs(bb.get("items"), "drive_count")).containsExactly(98L, 200L, 10L);

    JsonNode ssd = get("/v1/models?media=ssd").body();
    assertThat(texts(ssd.get("items"), "model")).containsExactly("MA1");

    JsonNode page1 = get("/v1/models?page=1&size=2").body();
    assertThat(page1.get("total").asLong()).isEqualTo(4);
    assertThat(texts(page1.get("items"), "model")).containsExactly("MODEL_B", "MODEL_C");
  }

  // ------------------------------------------------------------------ FR-API-2 cohort AFR

  @Test
  void afrByQuarterMatchesTruth() throws Exception {
    Reply r = get("/v1/cohorts/backblaze/MODEL_A/afr?from=2026-01-01&to=2026-06-30");
    assertThat(r.status()).isEqualTo(200);
    JsonNode body = r.body();
    assertThat(body.get("source").asString()).isEqualTo("backblaze");
    assertThat(body.get("model").asString()).isEqualTo("MODEL_A");
    assertThat(body.get("method").asString()).isEqualTo("exact_poisson_95");
    assertThat(body.get("generated_at").asString()).matches("\\d{4}-\\d{2}-\\d{2}T.*Z");

    JsonNode series = body.get("series");
    assertThat(texts(series, "period")).containsExactly("2026Q1", "2026Q2");
    assertPoint(series.get(0), 9000, 1, 36500.0 / 9000.0);
    assertPoint(series.get(1), 9098, 2, 73000.0 / 9098.0);
  }

  @Test
  void afrByMonthMatchesTruthAndClipsToWindow() throws Exception {
    JsonNode series =
        get("/v1/cohorts/backblaze/MODEL_A/afr?from=2026-02-01&to=2026-05-31&granularity=month")
            .body()
            .get("series");
    assertThat(texts(series, "period")).containsExactly("2026-02", "2026-03", "2026-04", "2026-05");
    assertPoint(series.get(0), 2800, 1, 36500.0 / 2800.0);
    assertPoint(series.get(1), 3100, 0, 0.0);
    assertPoint(series.get(2), 3000, 0, 0.0);
    assertPoint(series.get(3), 3100, 2, 73000.0 / 3100.0);
  }

  @Test
  void afrForUnknownModelIsNotFoundProblem() throws Exception {
    Reply r = get("/v1/cohorts/backblaze/NOPE/afr?from=2026-01-01&to=2026-06-30");
    assertProblem(r, 404);
    assertThat(r.body().get("detail").asString()).contains("NOPE");
  }

  // ------------------------------------------------------------------ FR-API-3 compare

  @Test
  void compareRanksQualifyingCohortsWithRateRatioVsFleet() throws Exception {
    Reply r = get("/v1/cohorts/compare?source=backblaze&from=2026-04-01&to=2026-06-30");
    assertThat(r.status()).isEqualTo(200);
    JsonNode body = r.body();
    assertThat(body.get("min_drives").asInt()).isEqualTo(60);
    assertThat(body.get("method").asString()).isEqualTo("exact_poisson_95");
    double fleetAfr = 5 * 36500.0 / 28208.0; // all three backblaze models in Q2
    assertThat(body.get("fleet_afr_pct").asDouble()).isCloseTo(fleetAfr, within(TOL * fleetAfr));

    // MODEL_C has only 10 drives on its last day, below the default min_drives of 60.
    JsonNode cohorts = body.get("cohorts");
    assertThat(texts(cohorts, "model")).containsExactly("MODEL_A", "MODEL_B");
    assertPoint(cohorts.get(0), 9098, 2, 73000.0 / 9098.0);
    assertPoint(cohorts.get(1), 18200, 2, 73000.0 / 18200.0);
    double ratioA = (73000.0 / 9098.0) / fleetAfr;
    assertThat(cohorts.get(0).get("rate_ratio_vs_fleet").asDouble())
        .isCloseTo(ratioA, within(TOL * ratioA));
  }

  @Test
  void compareMinDrivesUsesLastDayInWindowAndLimitCuts() throws Exception {
    String base = "/v1/cohorts/compare?source=backblaze&from=2026-04-01&to=2026-06-30";
    assertThat(texts(get(base + "&min_drives=5").body().get("cohorts"), "model"))
        .containsExactly("MODEL_C", "MODEL_A", "MODEL_B");
    assertThat(texts(get(base + "&min_drives=98").body().get("cohorts"), "model"))
        .containsExactly("MODEL_A", "MODEL_B");
    assertThat(texts(get(base + "&min_drives=99").body().get("cohorts"), "model"))
        .containsExactly("MODEL_B");
    assertThat(texts(get(base + "&min_drives=5&limit=1").body().get("cohorts"), "model"))
        .containsExactly("MODEL_C");
  }

  // ------------------------------------------------------------------ fleet summary

  @Test
  void fleetSummaryTotals() throws Exception {
    JsonNode body = get("/v1/fleet/summary?source=backblaze&from=2026-04-01&to=2026-06-30").body();
    assertThat(body.get("drives").asLong()).isEqualTo(6);
    assertPoint(body, 28208, 5, 5 * 36500.0 / 28208.0);
    assertThat(body.get("method").asString()).isEqualTo("exact_poisson_95");
  }

  // ------------------------------------------------------------------ FR-API-4 smart trend

  @Test
  void smartTrendUsesSampledDrivesOnly() throws Exception {
    JsonNode q =
        get("/v1/cohorts/backblaze/MODEL_A/smart-trend?attr=5&from=2026-04-01&to=2026-06-30")
            .body();
    assertThat(q.get("attr").asInt()).isEqualTo(5);
    JsonNode s = q.get("series");
    assertThat(s.size()).isEqualTo(1);
    assertTrend(s.get(0), "2026Q2", 4.0, 11.6, 0.6, 2);

    JsonNode m =
        get("/v1/cohorts/backblaze/MODEL_A/smart-trend?attr=5&from=2026-04-01&to=2026-06-30"
                + "&granularity=month")
            .body()
            .get("series");
    assertThat(m.size()).isEqualTo(2);
    assertTrend(m.get(0), "2026-05", 5.0, 11.7, 0.5, 2);
    assertTrend(m.get(1), "2026-06", 4.0, 4.0, 1.0, 1);
  }

  @Test
  void smartTrendRejectsAttributeNotKeptForSource() throws Exception {
    assertProblem(
        get("/v1/cohorts/backblaze/MODEL_A/smart-trend?attr=171&from=2026-04-01&to=2026-06-30"),
        400);
  }

  // ------------------------------------------------------------------ FR-API-5 failed drives

  @Test
  void failedDrivesListsAgeAndLastSmartValues() throws Exception {
    JsonNode body =
        get("/v1/cohorts/backblaze/MODEL_A/failed-drives?from=2026-01-01&to=2026-06-30").body();
    assertThat(body.get("total").asLong()).isEqualTo(3);
    JsonNode items = body.get("items");
    assertThat(texts(items, "drive_id")).containsExactly("A-1", "A-2", "A-3");
    assertThat(texts(items, "failed_on")).containsExactly("2026-02-10", "2026-05-05", "2026-05-05");
    assertThat(longs(items, "age_days")).containsExactly(40L, 124L, 65L);

    JsonNode a2 = items.get(1).get("last_smart");
    assertThat(a2.size()).isEqualTo(2);
    assertThat(a2.get("5").asDouble()).isEqualTo(12.0);
    assertThat(a2.get("197").asDouble()).isEqualTo(3.0);
    assertThat(items.get(2).get("last_smart").get("5").asDouble()).isEqualTo(100.0);
  }

  @Test
  void failedDrivesPaginates() throws Exception {
    String base = "/v1/cohorts/backblaze/MODEL_A/failed-drives?from=2026-01-01&to=2026-06-30";
    JsonNode p0 = get(base + "&page=0&size=2").body();
    assertThat(texts(p0.get("items"), "drive_id")).containsExactly("A-1", "A-2");
    assertThat(p0.get("total").asLong()).isEqualTo(3);
    JsonNode p1 = get(base + "&page=1&size=2").body();
    assertThat(texts(p1.get("items"), "drive_id")).containsExactly("A-3");
    assertThat(p1.get("page").asInt()).isEqualTo(1);
  }

  // ------------------------------------------------------------------ FR-API-6 alerts

  @Test
  void alertsListWithAllFieldsAndFilters() throws Exception {
    JsonNode all = get("/v1/alerts").body().get("items");
    assertThat(texts(all, "id"))
        .containsExactly(
            "00000000-0000-0000-0000-0000000000a1", "00000000-0000-0000-0000-0000000000a2");
    JsonNode open = all.get(0);
    assertThat(open.get("model").asString()).isEqualTo("MODEL_B");
    assertThat(open.get("source").asString()).isEqualTo("backblaze");
    assertThat(open.get("window_start").asString()).isEqualTo("2026-04-01");
    assertThat(open.get("window_end").asString()).isEqualTo("2026-06-30");
    assertThat(open.get("rate_ratio").asDouble()).isEqualTo(2.67);
    assertThat(open.get("p_value").asDouble()).isEqualTo(0.01);
    assertThat(open.get("status").asString()).isEqualTo("open");
    assertThat(open.get("resolved_at").isNull()).isTrue();

    assertThat(texts(get("/v1/alerts?status=resolved").body().get("items"), "model"))
        .containsExactly("MODEL_A");
    assertThat(get("/v1/alerts?source=alibaba").body().get("items").size()).isZero();
  }

  // ------------------------------------------------------------------ FR-API-8, RFC 9457

  @Test
  void windowOfEightQuartersIsAcceptedAndNineRejected() throws Exception {
    assertThat(get("/v1/cohorts/backblaze/MODEL_A/afr?from=2024-07-01&to=2026-06-30").status())
        .isEqualTo(200);
    Reply r = get("/v1/cohorts/backblaze/MODEL_A/afr?from=2024-04-01&to=2026-06-30");
    assertProblem(r, 400);
    assertThat(r.body().get("detail").asString()).contains("9 quarters");
  }

  @Test
  void pageSizeOf500IsAcceptedAnd501Rejected() throws Exception {
    assertThat(get("/v1/models?size=500").status()).isEqualTo(200);
    assertProblem(get("/v1/models?size=501"), 400);
  }

  @Test
  void badParametersAreProblemDetails() throws Exception {
    assertProblem(get("/v1/cohorts/nowhere/MODEL_A/afr?from=2026-01-01&to=2026-06-30"), 400);
    assertProblem(get("/v1/cohorts/backblaze/MODEL_A/afr?from=2026-13-01&to=2026-06-30"), 400);
    assertProblem(get("/v1/cohorts/backblaze/MODEL_A/afr?from=2026-01-01"), 400);
    assertProblem(
        get("/v1/cohorts/compare?source=backblaze&from=2026-04-01&to=2026-06-30&limit=51"), 400);
    assertProblem(get("/v1/alerts?status=closed"), 400);
    assertProblem(get("/v1/no-such-endpoint"), 404);
  }

  // ------------------------------------------------------------------ FR-OPS-4

  @Test
  void livenessAndReadinessAreUp() throws Exception {
    assertThat(get("/actuator/health").body().get("status").asString()).isEqualTo("UP");
    assertThat(get("/actuator/health/liveness").body().get("status").asString()).isEqualTo("UP");
    assertThat(get("/actuator/health/readiness").body().get("status").asString()).isEqualTo("UP");
  }

  // ------------------------------------------------------------------ helpers

  private static void assertPoint(JsonNode p, long driveDays, long failures, double afrPct) {
    assertThat(p.get("drive_days").asLong()).isEqualTo(driveDays);
    assertThat(p.get("failures").asLong()).isEqualTo(failures);
    assertThat(p.get("afr_pct").asDouble()).isCloseTo(afrPct, within(TOL * Math.max(afrPct, 1)));
    // The interval itself is verified against SciPy in AfrMathTest (FR-ANA-1).
    AfrEstimate ci = AfrMath.estimate95(failures, driveDays);
    assertThat(p.get("ci_low_pct").asDouble()).isEqualTo(ci.ciLowPct());
    assertThat(p.get("ci_high_pct").asDouble()).isEqualTo(ci.ciHighPct());
  }

  private static void assertTrend(
      JsonNode p, String period, double p50, double p95, double share, long nDrives) {
    assertThat(p.get("period").asString()).isEqualTo(period);
    assertThat(p.get("p50").asDouble()).isCloseTo(p50, within(TOL));
    assertThat(p.get("p95").asDouble()).isCloseTo(p95, within(TOL));
    assertThat(p.get("nonzero_share").asDouble()).isCloseTo(share, within(TOL));
    assertThat(p.get("n_drives").asLong()).isEqualTo(nDrives);
  }

  private static void assertProblem(Reply r, int status) {
    assertThat(r.status()).isEqualTo(status);
    assertThat(r.contentType()).startsWith("application/problem+json");
    assertThat(r.body().get("status").asInt()).isEqualTo(status);
    assertThat(r.body().get("title").asString()).isNotBlank();
    assertThat(r.body().has("detail")).isTrue();
  }

  private static List<String> texts(JsonNode array, String field) {
    List<String> out = new ArrayList<>();
    for (int i = 0; i < array.size(); i++) {
      out.add(array.get(i).get(field).asString());
    }
    return out;
  }

  private static List<Long> longs(JsonNode array, String field) {
    List<Long> out = new ArrayList<>();
    for (int i = 0; i < array.size(); i++) {
      out.add(array.get(i).get(field).asLong());
    }
    return out;
  }
}
