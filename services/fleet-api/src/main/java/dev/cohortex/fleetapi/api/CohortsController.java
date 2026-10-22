package dev.cohortex.fleetapi.api;

import dev.cohortex.fleetapi.api.Dtos.AfrSeries;
import dev.cohortex.fleetapi.api.Dtos.CompareResult;
import dev.cohortex.fleetapi.api.Dtos.FailedDrivePage;
import dev.cohortex.fleetapi.api.Dtos.SmartTrend;
import dev.cohortex.fleetapi.web.Params;
import dev.cohortex.fleetapi.web.Source;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import java.time.LocalDate;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.format.annotation.DateTimeFormat.ISO;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Cohort endpoints: AFR series, comparison, SMART trend and failed drives (contracts §4). */
@RestController
@RequestMapping("/v1/cohorts")
@Tag(name = "cohorts")
public class CohortsController {

  private final CohortService cohorts;

  public CohortsController(CohortService cohorts) {
    this.cohorts = cohorts;
  }

  @GetMapping("/{source}/{model}/afr")
  @Operation(
      summary = "AFR series of one cohort with exact Poisson 95% intervals",
      description =
          "Drive-days, failures and AFR (percent) per quarter or month inside [from, to]."
              + " Windows longer than 8 quarters are rejected with 400.")
  public AfrSeries afr(
      @PathVariable("source") String source,
      @PathVariable("model") String model,
      @Parameter(description = "First day, inclusive (ISO date)")
          @RequestParam("from")
          @DateTimeFormat(iso = ISO.DATE)
          LocalDate from,
      @Parameter(description = "Last day, inclusive (ISO date)")
          @RequestParam("to")
          @DateTimeFormat(iso = ISO.DATE)
          LocalDate to,
      @Parameter(description = "quarter or month")
          @RequestParam(name = "granularity", defaultValue = "quarter")
          String granularity) {
    return cohorts.afr(
        Params.source(source), model, Params.window(from, to), Params.granularity(granularity));
  }

  @GetMapping("/compare")
  @Operation(
      summary = "Rank cohorts of a source by AFR with rate ratios against the fleet",
      description =
          "A model qualifies when its drive count on its last day inside the window is at least"
              + " min_drives. Ranked by afr_pct descending, ties by model ascending.")
  public CompareResult compare(
      @RequestParam("source") String source,
      @RequestParam("from") @DateTimeFormat(iso = ISO.DATE) LocalDate from,
      @RequestParam("to") @DateTimeFormat(iso = ISO.DATE) LocalDate to,
      @RequestParam(name = "min_drives", defaultValue = "60") int minDrives,
      @Parameter(description = "1..50") @RequestParam(name = "limit", defaultValue = "20")
          int limit) {
    return cohorts.compare(
        Params.source(source),
        Params.window(from, to),
        Params.minDrives(minDrives),
        Params.compareLimit(limit));
  }

  @GetMapping("/{source}/{model}/smart-trend")
  @Operation(
      summary = "SMART attribute trend over the 1% sampled drives",
      description =
          "p50 and p95 of the raw value, share of drive-days with a raw value above zero, and"
              + " the number of distinct sampled drives, per period.")
  public SmartTrend smartTrend(
      @PathVariable("source") String source,
      @PathVariable("model") String model,
      @Parameter(description = "A SMART attribute kept for the source (contracts §1)")
          @RequestParam("attr")
          int attr,
      @RequestParam("from") @DateTimeFormat(iso = ISO.DATE) LocalDate from,
      @RequestParam("to") @DateTimeFormat(iso = ISO.DATE) LocalDate to,
      @RequestParam(name = "granularity", defaultValue = "quarter") String granularity) {
    Source src = Params.source(source);
    return cohorts.smartTrend(
        src,
        model,
        Params.smartAttr(src, attr),
        Params.window(from, to),
        Params.granularity(granularity));
  }

  @GetMapping("/{source}/{model}/failed-drives")
  @Operation(
      summary = "Failed drives of a cohort with age at failure and last SMART values",
      description = "Ordered by failed_on then drive_id; pages of at most 500 rows.")
  public FailedDrivePage failedDrives(
      @PathVariable("source") String source,
      @PathVariable("model") String model,
      @RequestParam("from") @DateTimeFormat(iso = ISO.DATE) LocalDate from,
      @RequestParam("to") @DateTimeFormat(iso = ISO.DATE) LocalDate to,
      @RequestParam(name = "page", defaultValue = "0") int page,
      @RequestParam(name = "size", defaultValue = "100") int size) {
    return cohorts.failedDrives(
        Params.source(source), model, Params.window(from, to), Params.page(page, size));
  }
}
