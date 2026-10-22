package dev.cohortex.fleetapi.web;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.LocalDate;
import org.junit.jupiter.api.Test;

/** FR-API-8 boundaries and parameter parsing (pure unit tests). */
class ParamsTest {

  private static LocalDate d(String iso) {
    return LocalDate.parse(iso);
  }

  // ---- window: at most 8 calendar quarters from quarter(from) to quarter(to), inclusive

  @Test
  void windowOfExactlyEightQuartersIsAccepted() {
    Window w = Params.window(d("2024-01-01"), d("2025-12-31"));
    assertThat(w.quarters()).isEqualTo(8);
  }

  @Test
  void windowOfNineQuartersIsRejected() {
    assertThatThrownBy(() -> Params.window(d("2024-01-01"), d("2026-01-01")))
        .isInstanceOf(BadRequestException.class)
        .hasMessageContaining("9 quarters");
  }

  @Test
  void windowCountsCalendarQuartersNotDays() {
    // Last day of 2024Q1 to first day of 2025Q4 touches 8 quarters.
    assertThat(Params.window(d("2024-03-31"), d("2025-10-01")).quarters()).isEqualTo(8);
    // Last day of 2024Q1 to first day of 2026Q1 touches 9 quarters.
    assertThatThrownBy(() -> Params.window(d("2024-03-31"), d("2026-01-01")))
        .isInstanceOf(BadRequestException.class);
  }

  @Test
  void singleDayWindowIsOneQuarter() {
    assertThat(Params.window(d("2026-05-05"), d("2026-05-05")).quarters()).isEqualTo(1);
  }

  @Test
  void windowEndingBeforeItStartsIsRejected() {
    assertThatThrownBy(() -> Params.window(d("2026-06-30"), d("2026-04-01")))
        .isInstanceOf(BadRequestException.class)
        .hasMessageContaining("before");
  }

  // ---- pagination: page >= 0, 1 <= size <= 500

  @Test
  void pageSizeOf500IsAccepted() {
    PageParams p = Params.page(3, 500);
    assertThat(p.size()).isEqualTo(500);
    assertThat(p.offset()).isEqualTo(1500L);
  }

  @Test
  void pageSizeOf501IsRejected() {
    assertThatThrownBy(() -> Params.page(0, 501))
        .isInstanceOf(BadRequestException.class)
        .hasMessageContaining("500");
  }

  @Test
  void pageSizeBelowOneAndNegativePageAreRejected() {
    assertThatThrownBy(() -> Params.page(0, 0)).isInstanceOf(BadRequestException.class);
    assertThatThrownBy(() -> Params.page(-1, 10)).isInstanceOf(BadRequestException.class);
  }

  // ---- compare limit (<= 50) and min_drives (>= 0)

  @Test
  void compareLimitBoundaries() {
    assertThat(Params.compareLimit(50)).isEqualTo(50);
    assertThat(Params.compareLimit(1)).isEqualTo(1);
    assertThatThrownBy(() -> Params.compareLimit(51)).isInstanceOf(BadRequestException.class);
    assertThatThrownBy(() -> Params.compareLimit(0)).isInstanceOf(BadRequestException.class);
  }

  @Test
  void minDrivesMustNotBeNegative() {
    assertThat(Params.minDrives(0)).isZero();
    assertThatThrownBy(() -> Params.minDrives(-1)).isInstanceOf(BadRequestException.class);
  }

  // ---- enumerations

  @Test
  void parsesSourcesMediaGranularitiesAndStatuses() {
    assertThat(Params.source("backblaze")).isEqualTo(Source.BACKBLAZE);
    assertThat(Params.source("alibaba")).isEqualTo(Source.ALIBABA);
    assertThat(Params.media("ssd")).isEqualTo("ssd");
    assertThat(Params.granularity("quarter")).isEqualTo(Granularity.QUARTER);
    assertThat(Params.granularity("month")).isEqualTo(Granularity.MONTH);
    assertThat(Params.alertStatus("open")).isEqualTo("open");
    assertThatThrownBy(() -> Params.source("seagate")).isInstanceOf(BadRequestException.class);
    assertThatThrownBy(() -> Params.media("tape")).isInstanceOf(BadRequestException.class);
    assertThatThrownBy(() -> Params.granularity("week")).isInstanceOf(BadRequestException.class);
    assertThatThrownBy(() -> Params.alertStatus("closed"))
        .isInstanceOf(BadRequestException.class);
  }

  @Test
  void smartAttributeMustBeKeptForTheSource() {
    assertThat(Params.smartAttr(Source.BACKBLAZE, 197)).isEqualTo(197);
    assertThat(Params.smartAttr(Source.ALIBABA, 171)).isEqualTo(171);
    assertThatThrownBy(() -> Params.smartAttr(Source.BACKBLAZE, 171))
        .isInstanceOf(BadRequestException.class);
    assertThatThrownBy(() -> Params.smartAttr(Source.ALIBABA, 197))
        .isInstanceOf(BadRequestException.class);
  }

  @Test
  void periodLabels() {
    assertThat(Granularity.QUARTER.label(d("2026-04-01"))).isEqualTo("2026Q2");
    assertThat(Granularity.QUARTER.label(d("2026-12-31"))).isEqualTo("2026Q4");
    assertThat(Granularity.MONTH.label(d("2026-05-01"))).isEqualTo("2026-05");
  }
}
