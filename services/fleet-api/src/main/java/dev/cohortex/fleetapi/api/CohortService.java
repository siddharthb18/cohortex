package dev.cohortex.fleetapi.api;

import dev.cohortex.fleetapi.afr.AfrEstimate;
import dev.cohortex.fleetapi.afr.AfrMath;
import dev.cohortex.fleetapi.api.Dtos.AfrPoint;
import dev.cohortex.fleetapi.api.Dtos.AfrSeries;
import dev.cohortex.fleetapi.api.Dtos.CompareItem;
import dev.cohortex.fleetapi.api.Dtos.CompareResult;
import dev.cohortex.fleetapi.api.Dtos.FailedDrivePage;
import dev.cohortex.fleetapi.api.Dtos.FleetSummary;
import dev.cohortex.fleetapi.api.Dtos.SmartTrend;
import dev.cohortex.fleetapi.api.Dtos.SmartTrendPoint;
import dev.cohortex.fleetapi.store.FleetStore;
import dev.cohortex.fleetapi.store.FleetStore.FleetTotals;
import dev.cohortex.fleetapi.store.FleetStore.ModelWindowTotals;
import dev.cohortex.fleetapi.web.Granularity;
import dev.cohortex.fleetapi.web.NotFoundException;
import dev.cohortex.fleetapi.web.PageParams;
import dev.cohortex.fleetapi.web.Source;
import dev.cohortex.fleetapi.web.Window;
import java.time.Clock;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Comparator;
import java.util.List;
import org.springframework.stereotype.Service;

/** Cohort and fleet answers: SQL totals from {@link FleetStore}, AFR math from {@link AfrMath}. */
@Service
public class CohortService {

  private final FleetStore store;
  private final Clock clock;

  public CohortService(FleetStore store, Clock clock) {
    this.store = store;
    this.clock = clock;
  }

  public AfrSeries afr(Source source, String model, Window window, Granularity granularity) {
    int modelId = requireModel(source, model);
    List<AfrPoint> series =
        store.cohortPeriods(modelId, window, granularity).stream()
            .map(
                p -> {
                  AfrEstimate e = AfrMath.estimate95(p.failures(), p.driveDays());
                  return new AfrPoint(
                      granularity.label(p.periodStart()),
                      p.driveDays(),
                      p.failures(),
                      e.afrPct(),
                      e.ciLowPct(),
                      e.ciHighPct());
                })
            .toList();
    return new AfrSeries(source.id(), model, series, AfrMath.METHOD_95, now());
  }

  public CompareResult compare(Source source, Window window, int minDrives, int limit) {
    List<ModelWindowTotals> totals = store.modelWindowTotals(source, window);
    long fleetDriveDays = totals.stream().mapToLong(ModelWindowTotals::driveDays).sum();
    long fleetFailures = totals.stream().mapToLong(ModelWindowTotals::failures).sum();
    Double fleetAfr = fleetDriveDays > 0 ? AfrMath.afrPct(fleetFailures, fleetDriveDays) : null;
    return new CompareResult(
        source.id(),
        window.from(),
        window.to(),
        minDrives,
        fleetAfr,
        rank(totals, fleetAfr, minDrives, limit),
        AfrMath.METHOD_95,
        now());
  }

  /**
   * Keeps models whose drive count on their last day in the window is at least {@code minDrives},
   * ranks them by AFR descending (ties by model name ascending) and keeps the first {@code limit}.
   * {@code rate_ratio_vs_fleet} is the model AFR divided by the fleet AFR, or null when the fleet
   * AFR is null or zero.
   */
  static List<CompareItem> rank(
      List<ModelWindowTotals> totals, Double fleetAfr, int minDrives, int limit) {
    return totals.stream()
        .filter(t -> t.lastDayDriveCount() >= minDrives && t.driveDays() > 0)
        .map(
            t -> {
              AfrEstimate e = AfrMath.estimate95(t.failures(), t.driveDays());
              Double ratio = fleetAfr == null || fleetAfr == 0.0 ? null : e.afrPct() / fleetAfr;
              return new CompareItem(
                  t.model(),
                  t.driveDays(),
                  t.failures(),
                  e.afrPct(),
                  e.ciLowPct(),
                  e.ciHighPct(),
                  ratio);
            })
        .sorted(
            Comparator.comparingDouble(CompareItem::afrPct)
                .reversed()
                .thenComparing(CompareItem::model))
        .limit(limit)
        .toList();
  }

  public FleetSummary fleetSummary(Source source, Window window) {
    FleetTotals t = store.fleetTotals(source, window);
    AfrEstimate e = t.driveDays() > 0 ? AfrMath.estimate95(t.failures(), t.driveDays()) : null;
    return new FleetSummary(
        source.id(),
        window.from(),
        window.to(),
        t.drives(),
        t.driveDays(),
        t.failures(),
        e == null ? null : e.afrPct(),
        e == null ? null : e.ciLowPct(),
        e == null ? null : e.ciHighPct(),
        AfrMath.METHOD_95,
        now());
  }

  public SmartTrend smartTrend(
      Source source, String model, int attr, Window window, Granularity granularity) {
    int modelId = requireModel(source, model);
    List<SmartTrendPoint> series =
        store.smartTrend(source, modelId, attr, window, granularity).stream()
            .map(
                r ->
                    new SmartTrendPoint(
                        granularity.label(r.periodStart()),
                        r.p50(),
                        r.p95(),
                        r.nonzeroShare(),
                        r.nDrives()))
            .toList();
    return new SmartTrend(source.id(), model, attr, series, now());
  }

  public FailedDrivePage failedDrives(Source source, String model, Window window, PageParams page) {
    int modelId = requireModel(source, model);
    return new FailedDrivePage(
        store.failedDrives(source, modelId, window, page),
        page.page(),
        page.size(),
        store.countFailedDrives(modelId, window));
  }

  private int requireModel(Source source, String model) {
    return store
        .modelId(source, model)
        .orElseThrow(
            () -> new NotFoundException("unknown model '" + model + "' for source " + source.id()));
  }

  private Instant now() {
    return clock.instant().truncatedTo(ChronoUnit.SECONDS);
  }
}
