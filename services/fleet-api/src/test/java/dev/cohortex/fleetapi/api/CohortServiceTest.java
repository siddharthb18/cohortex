package dev.cohortex.fleetapi.api;

import static org.assertj.core.api.Assertions.assertThat;

import dev.cohortex.fleetapi.api.Dtos.CompareItem;
import dev.cohortex.fleetapi.store.FleetStore.ModelWindowTotals;
import java.util.List;
import org.junit.jupiter.api.Test;

/** FR-API-3 ranking rules (implementation-notes §5) as a pure unit test. */
class CohortServiceTest {

  private static final List<ModelWindowTotals> TOTALS =
      List.of(
          new ModelWindowTotals("B", 36_500, 2, 100), // AFR 2.0
          new ModelWindowTotals("A", 36_500, 2, 100), // AFR 2.0, ties with B
          new ModelWindowTotals("C", 36_500, 4, 59), // AFR 4.0 but 59 drives on its last day
          new ModelWindowTotals("D", 36_500, 1, 60)); // AFR 1.0, exactly min_drives

  @Test
  void ranksByAfrDescendingThenModelAndAppliesMinDrives() {
    List<CompareItem> ranked = CohortService.rank(TOTALS, 2.5, 60, 20);
    assertThat(ranked).extracting(CompareItem::model).containsExactly("A", "B", "D");
    assertThat(ranked.get(0).afrPct()).isEqualTo(2.0);
    assertThat(ranked.get(0).rateRatioVsFleet()).isEqualTo(2.0 / 2.5);
  }

  @Test
  void limitCutsAfterRanking() {
    assertThat(CohortService.rank(TOTALS, 2.5, 0, 2))
        .extracting(CompareItem::model)
        .containsExactly("C", "A");
  }

  @Test
  void rateRatioIsNullWhenFleetAfrIsZeroOrMissing() {
    assertThat(CohortService.rank(TOTALS, 0.0, 0, 1).get(0).rateRatioVsFleet()).isNull();
    assertThat(CohortService.rank(TOTALS, null, 0, 1).get(0).rateRatioVsFleet()).isNull();
  }
}
