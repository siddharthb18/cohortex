package dev.cohortex.fleetapi.web;

import java.time.LocalDate;

/**
 * A validated, inclusive date window {@code [from, to]}.
 *
 * @param from first day, inclusive
 * @param to last day, inclusive
 * @param quarters number of calendar quarters from {@code quarter(from)} to {@code quarter(to)}
 */
public record Window(LocalDate from, LocalDate to, int quarters) {

  /** Calendar quarters touched by {@code [from, to]}, counting both ends. */
  static int quartersSpanned(LocalDate from, LocalDate to) {
    return quarterIndex(to) - quarterIndex(from) + 1;
  }

  private static int quarterIndex(LocalDate day) {
    return day.getYear() * 4 + (day.getMonthValue() - 1) / 3;
  }
}
