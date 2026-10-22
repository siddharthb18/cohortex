package dev.cohortex.fleetapi.afr;

import org.apache.commons.statistics.distribution.ChiSquaredDistribution;

/**
 * Annualized failure rate with an exact (Garwood) Poisson confidence interval (ADR-007,
 * implementation-notes §4). The Python side (mcp-stats) uses the same formulas with SciPy; both are
 * checked against {@code contracts/fixtures/afr_ci_cases.json} (FR-ANA-1).
 *
 * <ul>
 *   <li>{@code afr_pct = failures * 365 * 100 / drive_days}
 *   <li>{@code a = (1 - confidence) / 2}
 *   <li>lower count {@code = chi2.ppf(a, 2k) / 2}, or 0 when {@code k = 0}
 *   <li>upper count {@code = chi2.ppf(1 - a, 2k + 2) / 2}
 *   <li>each count is converted to percent with the same factor as the AFR
 * </ul>
 */
public final class AfrMath {

  /** The method label carried by every AFR-bearing response. */
  public static final String METHOD_95 = "exact_poisson_95";

  /** Confidence level used by the API. */
  public static final double CONFIDENCE_95 = 0.95;

  private AfrMath() {}

  /** Point AFR in percent. Integer product first, then one division, exactly like Python. */
  public static double afrPct(long failures, long driveDays) {
    checkCounts(failures, driveDays);
    return (double) (failures * 365L * 100L) / (double) driveDays;
  }

  /** AFR with the 95% exact Poisson interval. */
  public static AfrEstimate estimate95(long failures, long driveDays) {
    return estimate(failures, driveDays, CONFIDENCE_95);
  }

  /** AFR with an exact Poisson interval at the given two-sided confidence level. */
  public static AfrEstimate estimate(long failures, long driveDays, double confidence) {
    checkCounts(failures, driveDays);
    if (!(confidence > 0.0 && confidence < 1.0)) {
      throw new IllegalArgumentException("confidence must be in (0, 1), got " + confidence);
    }
    double a = (1.0 - confidence) / 2.0;
    double lowerCount =
        failures == 0
            ? 0.0
            : ChiSquaredDistribution.of(2.0 * failures).inverseCumulativeProbability(a) / 2.0;
    double upperCount =
        ChiSquaredDistribution.of(2.0 * failures + 2.0).inverseCumulativeProbability(1.0 - a) / 2.0;
    return new AfrEstimate(
        afrPct(failures, driveDays), toPct(lowerCount, driveDays), toPct(upperCount, driveDays));
  }

  /** Same operation order as the Python reference: {@code count * 365 * 100 / drive_days}. */
  private static double toPct(double count, long driveDays) {
    return count * 365 * 100 / driveDays;
  }

  private static void checkCounts(long failures, long driveDays) {
    if (failures < 0) {
      throw new IllegalArgumentException("failures must be >= 0, got " + failures);
    }
    if (driveDays <= 0) {
      throw new IllegalArgumentException("drive_days must be > 0, got " + driveDays);
    }
  }
}
