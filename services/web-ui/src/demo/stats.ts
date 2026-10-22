/**
 * Statistics for the static demo only (synthetic data). The real numbers come from fleet-api and
 * mcp-stats; this mirrors implementation-notes §4 closely enough to keep demo files consistent.
 * No imports, so the Node data generator can load this file directly.
 */

function gammaln(x: number): number {
  const c = [
    676.5203681218851, -1259.1392167224028, 771.32342877765313, -176.61502916214059,
    12.507343278686905, -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7,
  ];
  if (x < 0.5) return Math.log(Math.PI / Math.sin(Math.PI * x)) - gammaln(1 - x);
  const xx = x - 1;
  let a = 0.99999999999980993;
  const t = xx + 7.5;
  for (let i = 0; i < c.length; i += 1) a += (c[i] ?? 0) / (xx + i + 1);
  return 0.5 * Math.log(2 * Math.PI) + (xx + 0.5) * Math.log(t) - t + Math.log(a);
}

/** Regularized lower incomplete gamma P(a, x). */
function gammaP(a: number, x: number): number {
  if (x <= 0) return 0;
  if (x < a + 1) {
    let sum = 1 / a;
    let term = sum;
    for (let n = 1; n < 1000; n += 1) {
      term *= x / (a + n);
      sum += term;
      if (Math.abs(term) < Math.abs(sum) * 1e-15) break;
    }
    return sum * Math.exp(-x + a * Math.log(x) - gammaln(a));
  }
  // Continued fraction for Q(a, x) (Lentz).
  let b = x + 1 - a;
  let c = 1 / 1e-300;
  let d = 1 / b;
  let h = d;
  for (let i = 1; i < 1000; i += 1) {
    const an = -i * (i - a);
    b += 2;
    d = an * d + b;
    if (Math.abs(d) < 1e-300) d = 1e-300;
    c = b + an / c;
    if (Math.abs(c) < 1e-300) c = 1e-300;
    d = 1 / d;
    const delta = d * c;
    h *= delta;
    if (Math.abs(delta - 1) < 1e-15) break;
  }
  return 1 - Math.exp(-x + a * Math.log(x) - gammaln(a)) * h;
}

/** Root of a monotonic function on [lo, hi] (increasing or decreasing). */
function bisect(f: (x: number) => number, lo: number, hi: number): number {
  let a = lo;
  let b = hi;
  const signLo = Math.sign(f(lo));
  for (let i = 0; i < 200; i += 1) {
    const mid = (a + b) / 2;
    if (Math.sign(f(mid)) === signLo) a = mid;
    else b = mid;
  }
  return (a + b) / 2;
}

/** Quantile of Gamma(shape, 1), i.e. chi2.ppf(q, 2 * shape) / 2. */
function gammaQuantile(q: number, shape: number): number {
  const hi = shape + 20 + 20 * Math.sqrt(shape);
  return bisect((x) => gammaP(shape, x) - q, 0, hi);
}

export function afrPct(failures: number, driveDays: number): number {
  return (failures * 365 * 100) / driveDays;
}

export function afrCi(
  failures: number,
  driveDays: number,
  confidence = 0.95,
): { afr_pct: number; ci_low_pct: number; ci_high_pct: number } {
  const a = (1 - confidence) / 2;
  const factor = (365 * 100) / driveDays;
  const low = failures === 0 ? 0 : gammaQuantile(a, failures);
  const high = gammaQuantile(1 - a, failures + 1);
  return {
    afr_pct: failures * factor,
    ci_low_pct: low * factor,
    ci_high_pct: high * factor,
  };
}

function logChoose(n: number, k: number): number {
  return gammaln(n + 1) - gammaln(k + 1) - gammaln(n - k + 1);
}

function binomPmf(k: number, n: number, p: number): number {
  if (p <= 0) return k === 0 ? 1 : 0;
  if (p >= 1) return k === n ? 1 : 0;
  return Math.exp(logChoose(n, k) + k * Math.log(p) + (n - k) * Math.log(1 - p));
}

function binomCdf(k: number, n: number, p: number): number {
  let s = 0;
  for (let i = 0; i <= k; i += 1) s += binomPmf(i, n, p);
  return Math.min(1, s);
}

/** Exact conditional binomial test of two Poisson rates (implementation-notes §4). */
export function compareRates(
  failuresA: number,
  driveDaysA: number,
  failuresB: number,
  driveDaysB: number,
  confidence = 0.95,
): { rate_ratio: number; ci_low: number; ci_high: number; p_value: number; method: string } {
  const n = failuresA + failuresB;
  const p0 = driveDaysA / (driveDaysA + driveDaysB);
  const observed = binomPmf(failuresA, n, p0);
  let p = 0;
  for (let i = 0; i <= n; i += 1) {
    const pi = binomPmf(i, n, p0);
    if (pi <= observed * (1 + 1e-7)) p += pi;
  }
  const a = (1 - confidence) / 2;
  const lowP = failuresA === 0 ? 0 : bisect((x) => a - (1 - binomCdf(failuresA - 1, n, x)), 0, 1);
  const highP = failuresA === n ? 1 : bisect((x) => binomCdf(failuresA, n, x) - a, 0, 1);
  const toRatio = (q: number) => (q / (1 - q)) * (driveDaysB / driveDaysA);
  return {
    rate_ratio: failuresA / driveDaysA / (failuresB / driveDaysB),
    ci_low: toRatio(lowP),
    ci_high: highP >= 1 ? Infinity : toRatio(highP),
    p_value: Math.min(1, p),
    method: 'exact_conditional_binomial',
  };
}
