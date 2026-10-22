package dev.cohortex.fleetapi.web;

/** A named resource (for example a drive model) does not exist; rendered as a 404 problem. */
public class NotFoundException extends RuntimeException {

  private static final long serialVersionUID = 1L;

  public NotFoundException(String message) {
    super(message);
  }
}
