package dev.cohortex.fleetapi.afr;

/**
 * An annualized failure rate with its exact Poisson confidence interval, all in percent.
 *
 * @param afrPct point estimate, {@code failures * 365 * 100 / drive_days}
 * @param ciLowPct lower bound of the interval
 * @param ciHighPct upper bound of the interval
 */
public record AfrEstimate(double afrPct, double ciLowPct, double ciHighPct) {}
