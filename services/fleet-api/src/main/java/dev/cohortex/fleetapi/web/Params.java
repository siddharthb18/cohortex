package dev.cohortex.fleetapi.web;

import java.time.LocalDate;
import java.util.Locale;

/**
 * Request-parameter validation (FR-API-8, implementation-notes §5). Every failure is a {@link
 * BadRequestException}, which the API renders as a 400 problem detail.
 */
public final class Params {

  /** Longest accepted window, in calendar quarters (FR-API-8). */
  public static final int MAX_WINDOW_QUARTERS = 8;

  /** Largest page (FR-API-8). */
  public static final int MAX_PAGE_SIZE = 500;

  /** Largest {@code limit} for {@code /v1/cohorts/compare} (contracts §4). */
  public static final int MAX_COMPARE_LIMIT = 50;

  private Params() {}

  public static Source source(String value) {
    for (Source s : Source.values()) {
      if (s.id().equals(value)) {
        return s;
      }
    }
    throw new BadRequestException("source must be one of backblaze, alibaba; got '" + value + "'");
  }

  public static String media(String value) {
    if ("hdd".equals(value) || "ssd".equals(value)) {
      return value;
    }
    throw new BadRequestException("media must be one of hdd, ssd; got '" + value + "'");
  }

  public static Granularity granularity(String value) {
    for (Granularity g : Granularity.values()) {
      if (g.id().equals(value)) {
        return g;
      }
    }
    throw new BadRequestException("granularity must be one of quarter, month; got '" + value + "'");
  }

  public static String alertStatus(String value) {
    if ("open".equals(value) || "resolved".equals(value)) {
      return value;
    }
    throw new BadRequestException("status must be one of open, resolved; got '" + value + "'");
  }

  /**
   * An inclusive window {@code [from, to]}. Rejected when {@code to < from} or when it touches more
   * than {@value #MAX_WINDOW_QUARTERS} calendar quarters.
   */
  public static Window window(LocalDate from, LocalDate to) {
    if (to.isBefore(from)) {
      throw new BadRequestException("to (" + to + ") is before from (" + from + ")");
    }
    int quarters = Window.quartersSpanned(from, to);
    if (quarters > MAX_WINDOW_QUARTERS) {
      throw new BadRequestException(
          String.format(
              Locale.ROOT,
              "window %s..%s spans %d quarters; at most %d are allowed",
              from,
              to,
              quarters,
              MAX_WINDOW_QUARTERS));
    }
    return new Window(from, to, quarters);
  }

  public static PageParams page(int page, int size) {
    if (page < 0) {
      throw new BadRequestException("page must be >= 0; got " + page);
    }
    if (size < 1 || size > MAX_PAGE_SIZE) {
      throw new BadRequestException(
          "size must be between 1 and " + MAX_PAGE_SIZE + "; got " + size);
    }
    return new PageParams(page, size);
  }

  public static int compareLimit(int limit) {
    if (limit < 1 || limit > MAX_COMPARE_LIMIT) {
      throw new BadRequestException(
          "limit must be between 1 and " + MAX_COMPARE_LIMIT + "; got " + limit);
    }
    return limit;
  }

  public static int minDrives(int minDrives) {
    if (minDrives < 0) {
      throw new BadRequestException("min_drives must be >= 0; got " + minDrives);
    }
    return minDrives;
  }

  /** A SMART attribute kept in the serving tables for this source (contracts §1). */
  public static int smartAttr(Source source, int attr) {
    if (!source.keepsSmartAttribute(attr)) {
      throw new BadRequestException(
          "attr " + attr + " is not a SMART attribute kept for source " + source.id());
    }
    return attr;
  }
}
