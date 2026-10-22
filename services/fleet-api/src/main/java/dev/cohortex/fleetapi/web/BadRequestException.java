package dev.cohortex.fleetapi.web;

/** A request parameter is invalid; rendered as a 400 problem detail (RFC 9457). */
public class BadRequestException extends RuntimeException {

  private static final long serialVersionUID = 1L;

  public BadRequestException(String message) {
    super(message);
  }
}
