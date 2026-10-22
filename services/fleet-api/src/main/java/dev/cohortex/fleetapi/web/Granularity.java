package dev.cohortex.fleetapi.web;

import java.time.LocalDate;
import java.time.YearMonth;

/** Series granularity; period labels follow implementation-notes §3 ({@code 2026Q2}, {@code 2026-05}). */
public enum Granularity {
  QUARTER("quarter"),
  MONTH("month");

  private final String id;

  Granularity(String id) {
    this.id = id;
  }

  /** The query-parameter value, also the PostgreSQL {@code date_trunc} unit. */
  public String id() {
    return id;
  }

  /** Label of the period that contains {@code day}. */
  public String label(LocalDate day) {
    return switch (this) {
      case QUARTER -> day.getYear() + "Q" + ((day.getMonthValue() - 1) / 3 + 1);
      case MONTH -> YearMonth.from(day).toString();
    };
  }
}
