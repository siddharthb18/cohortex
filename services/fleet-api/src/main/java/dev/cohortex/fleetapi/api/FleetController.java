package dev.cohortex.fleetapi.api;

import dev.cohortex.fleetapi.api.Dtos.AlertList;
import dev.cohortex.fleetapi.api.Dtos.FleetSummary;
import dev.cohortex.fleetapi.api.Dtos.ModelPage;
import dev.cohortex.fleetapi.store.FleetStore;
import dev.cohortex.fleetapi.web.PageParams;
import dev.cohortex.fleetapi.web.Params;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import java.time.Clock;
import java.time.LocalDate;
import java.time.temporal.ChronoUnit;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.format.annotation.DateTimeFormat.ISO;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Models, fleet summary and alerts (contracts §4). */
@RestController
@Tag(name = "fleet")
public class FleetController {

  private final FleetStore store;
  private final CohortService cohorts;
  private final Clock clock;

  public FleetController(FleetStore store, CohortService cohorts, Clock clock) {
    this.store = store;
    this.cohorts = cohorts;
    this.clock = clock;
  }

  @GetMapping("/v1/models")
  @Operation(
      summary = "List drive models",
      description = "drive_count is the model's drive count on its latest day in cohort_daily.")
  public ModelPage models(
      @RequestParam(name = "source", required = false) String source,
      @RequestParam(name = "media", required = false) String media,
      @RequestParam(name = "page", defaultValue = "0") int page,
      @RequestParam(name = "size", defaultValue = "100") int size) {
    String src = source == null ? null : Params.source(source).id();
    String med = media == null ? null : Params.media(media);
    PageParams p = Params.page(page, size);
    return new ModelPage(
        store.models(src, med, p), p.page(), p.size(), store.countModels(src, med));
  }

  @GetMapping("/v1/fleet/summary")
  @Operation(
      summary = "Fleet totals of a source in a window",
      description =
          "drives = distinct drives with first_seen <= to and last_seen >= from; drive-days,"
              + " failures and AFR with exact Poisson 95% interval over all models.")
  public FleetSummary fleetSummary(
      @RequestParam("source") String source,
      @RequestParam("from") @DateTimeFormat(iso = ISO.DATE) LocalDate from,
      @RequestParam("to") @DateTimeFormat(iso = ISO.DATE) LocalDate to) {
    return cohorts.fleetSummary(Params.source(source), Params.window(from, to));
  }

  @GetMapping("/v1/alerts")
  @Operation(summary = "List cohort alerts, newest first")
  public AlertList alerts(
      @RequestParam(name = "status", required = false) String status,
      @RequestParam(name = "source", required = false) String source) {
    String st = status == null ? null : Params.alertStatus(status);
    String src = source == null ? null : Params.source(source).id();
    return new AlertList(store.alerts(st, src), clock.instant().truncatedTo(ChronoUnit.SECONDS));
  }
}
