package dev.cohortex.fleetapi.api;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * Response bodies (contracts §4, implementation-notes §5). JSON names are snake_case and spelled
 * out with {@code @JsonProperty} so Jackson and the OpenAPI generator agree.
 */
public final class Dtos {

  private Dtos() {}

  /** One drive model. */
  public record ModelItem(
      int id,
      String source,
      String model,
      String media,
      @JsonProperty("capacity_bytes") Long capacityBytes,
      @JsonProperty("drive_count") long driveCount) {}

  /** {@code GET /v1/models}. */
  public record ModelPage(List<ModelItem> items, int page, int size, long total) {}

  /** One period of a cohort AFR series. */
  public record AfrPoint(
      String period,
      @JsonProperty("drive_days") long driveDays,
      long failures,
      @JsonProperty("afr_pct") double afrPct,
      @JsonProperty("ci_low_pct") double ciLowPct,
      @JsonProperty("ci_high_pct") double ciHighPct) {}

  /** {@code GET /v1/cohorts/{source}/{model}/afr}. */
  public record AfrSeries(
      String source,
      String model,
      List<AfrPoint> series,
      String method,
      @JsonProperty("generated_at") Instant generatedAt) {}

  /** One ranked cohort of {@code /v1/cohorts/compare}. */
  public record CompareItem(
      String model,
      @JsonProperty("drive_days") long driveDays,
      long failures,
      @JsonProperty("afr_pct") double afrPct,
      @JsonProperty("ci_low_pct") double ciLowPct,
      @JsonProperty("ci_high_pct") double ciHighPct,
      @JsonProperty("rate_ratio_vs_fleet") Double rateRatioVsFleet) {}

  /** {@code GET /v1/cohorts/compare}. */
  public record CompareResult(
      String source,
      LocalDate from,
      LocalDate to,
      @JsonProperty("min_drives") int minDrives,
      @JsonProperty("fleet_afr_pct") Double fleetAfrPct,
      List<CompareItem> cohorts,
      String method,
      @JsonProperty("generated_at") Instant generatedAt) {}

  /** One period of a SMART trend. */
  public record SmartTrendPoint(
      String period,
      Double p50,
      Double p95,
      @JsonProperty("nonzero_share") double nonzeroShare,
      @JsonProperty("n_drives") long nDrives) {}

  /** {@code GET /v1/cohorts/{source}/{model}/smart-trend}. */
  public record SmartTrend(
      String source,
      String model,
      int attr,
      List<SmartTrendPoint> series,
      @JsonProperty("generated_at") Instant generatedAt) {}

  /** One failed drive. {@code last_smart} maps attribute id to raw value on {@code failed_on}. */
  public record FailedDrive(
      @JsonProperty("drive_id") String driveId,
      @JsonProperty("failed_on") LocalDate failedOn,
      @JsonProperty("age_days") int ageDays,
      @JsonProperty("last_smart") Map<String, Double> lastSmart) {}

  /** {@code GET /v1/cohorts/{source}/{model}/failed-drives}. */
  public record FailedDrivePage(List<FailedDrive> items, int page, int size, long total) {}

  /** {@code GET /v1/fleet/summary}. AFR fields are null when the window has no drive-days. */
  public record FleetSummary(
      String source,
      LocalDate from,
      LocalDate to,
      long drives,
      @JsonProperty("drive_days") long driveDays,
      long failures,
      @JsonProperty("afr_pct") Double afrPct,
      @JsonProperty("ci_low_pct") Double ciLowPct,
      @JsonProperty("ci_high_pct") Double ciHighPct,
      String method,
      @JsonProperty("generated_at") Instant generatedAt) {}

  /** One alert row (DDL {@code alert}) with its model's source and name. */
  public record AlertItem(
      UUID id,
      @JsonProperty("model_id") int modelId,
      String source,
      String model,
      @JsonProperty("opened_at") OffsetDateTime openedAt,
      @JsonProperty("window_start") LocalDate windowStart,
      @JsonProperty("window_end") LocalDate windowEnd,
      @JsonProperty("baseline_afr") double baselineAfr,
      @JsonProperty("current_afr") double currentAfr,
      @JsonProperty("rate_ratio") double rateRatio,
      @JsonProperty("p_value") double pValue,
      String status,
      @JsonProperty("resolved_at") OffsetDateTime resolvedAt) {}

  /** {@code GET /v1/alerts}. */
  public record AlertList(
      List<AlertItem> items, @JsonProperty("generated_at") Instant generatedAt) {}
}
