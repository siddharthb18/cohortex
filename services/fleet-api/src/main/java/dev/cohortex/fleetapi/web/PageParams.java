package dev.cohortex.fleetapi.web;

/**
 * Validated pagination: {@code page} is 0-based, {@code size} is 1..500.
 *
 * @param page page number, 0-based
 * @param size rows per page
 */
public record PageParams(int page, int size) {

  /** Rows to skip. */
  public long offset() {
    return (long) page * size;
  }
}
