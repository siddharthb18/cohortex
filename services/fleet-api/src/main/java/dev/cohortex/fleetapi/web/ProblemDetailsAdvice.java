package dev.cohortex.fleetapi.web;

import jakarta.servlet.http.HttpServletRequest;
import java.net.URI;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler;

/**
 * Every error is an RFC 9457 {@code application/problem+json} body (FR-API-7). Spring's base class
 * already maps framework errors (missing or malformed parameters, unknown routes) to problem
 * details; this adds the API's own 400 and 404 cases and a 500 fallback without stack traces.
 */
@RestControllerAdvice
public class ProblemDetailsAdvice extends ResponseEntityExceptionHandler {

  private static final Logger log = LoggerFactory.getLogger(ProblemDetailsAdvice.class);

  @ExceptionHandler(BadRequestException.class)
  public ResponseEntity<ProblemDetail> badRequest(
      BadRequestException e, HttpServletRequest request) {
    return problem(HttpStatus.BAD_REQUEST, e.getMessage(), request);
  }

  @ExceptionHandler(NotFoundException.class)
  public ResponseEntity<ProblemDetail> notFound(NotFoundException e, HttpServletRequest request) {
    return problem(HttpStatus.NOT_FOUND, e.getMessage(), request);
  }

  @ExceptionHandler(Exception.class)
  public ResponseEntity<ProblemDetail> unexpected(Exception e, HttpServletRequest request) {
    log.error("Unhandled error on {}", request.getRequestURI(), e);
    return problem(HttpStatus.INTERNAL_SERVER_ERROR, "Internal error", request);
  }

  private static ResponseEntity<ProblemDetail> problem(
      HttpStatus status, String detail, HttpServletRequest request) {
    ProblemDetail body = ProblemDetail.forStatusAndDetail(status, detail);
    body.setInstance(URI.create(request.getRequestURI()));
    return ResponseEntity.status(status).body(body);
  }
}
