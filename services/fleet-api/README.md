# C3 fleet-api (Java)

Read-only REST API over the serving store: models, cohort AFR with exact Poisson CIs, comparisons,
SMART trends, failed drives, fleet totals and alerts. Spring Boot 4.1, Java 25, OpenAPI 3.1.

- **Built in:** WP-04 (see [build plan](/docs/specs/build-plan.md)); FR-API-1..8, FR-ANA-1 (Java side), FR-OPS-4.
- **Contract:** [`contracts/openapi/fleet-api.yaml`](/contracts/openapi/fleet-api.yaml) (hand-written,
  source of truth). The running service also serves its generated document at `/v3/api-docs`
  and Swagger UI at `/swagger-ui.html`.

## Endpoints

| Method and path | Parameters | Returns |
| --- | --- | --- |
| `GET /v1/models` | `source?`, `media?`, `page`, `size` | `{items: [{id, source, model, media, capacity_bytes, drive_count}], page, size, total}` |
| `GET /v1/cohorts/{source}/{model}/afr` | `from`, `to`, `granularity` (`quarter`/`month`) | `{source, model, series: [{period, drive_days, failures, afr_pct, ci_low_pct, ci_high_pct}], method, generated_at}` |
| `GET /v1/cohorts/compare` | `source`, `from`, `to`, `min_drives` (60), `limit` (20, ≤ 50) | `{source, from, to, min_drives, fleet_afr_pct, cohorts: [{model, drive_days, failures, afr_pct, ci_low_pct, ci_high_pct, rate_ratio_vs_fleet}], method, generated_at}` |
| `GET /v1/cohorts/{source}/{model}/smart-trend` | `attr`, `from`, `to`, `granularity` | `{source, model, attr, series: [{period, p50, p95, nonzero_share, n_drives}], generated_at}` |
| `GET /v1/cohorts/{source}/{model}/failed-drives` | `from`, `to`, `page`, `size` | `{items: [{drive_id, failed_on, age_days, last_smart}], page, size, total}` |
| `GET /v1/fleet/summary` | `source`, `from`, `to` | `{source, from, to, drives, drive_days, failures, afr_pct, ci_low_pct, ci_high_pct, method, generated_at}` |
| `GET /v1/alerts` | `status?`, `source?` | `{items: [alert rows + source, model], generated_at}` |
| `GET /actuator/health[/liveness\|/readiness]` | — | Health (readiness includes the database) |

Errors are RFC 9457 `application/problem+json`: 400 for a bad value, a window touching more than
8 calendar quarters, `to < from`, `size` outside 1..500, `limit` outside 1..50, or a SMART attribute
not kept for the source; 404 for an unknown model or route; 500 without a stack trace.

## Run it

```bash
make up                                     # Postgres + pgvector from deploy/compose
./gradlew :services:fleet-api:bootRun       # http://localhost:8080 ; Flyway applies db/migrations
curl 'localhost:8080/v1/cohorts/backblaze/ST12000NM000J/afr?from=2026-04-01&to=2026-06-30'
```

Configuration (environment variables; defaults in `src/main/resources/application.properties`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `POSTGRES_HOST` / `POSTGRES_PORT` / `POSTGRES_DB` | `localhost` / `5432` / `cohortex` | JDBC URL parts (`SPRING_DATASOURCE_URL` overrides the whole URL) |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` | `cohortex` / empty | Database credentials |
| `FLYWAY_LOCATIONS` | `filesystem:../../db/migrations` | Migration folder (the image uses `/app/db/migrations`) |
| `EMBEDDING_DIM` | `384` | Flyway placeholder `${embedding_dim}` in V1 |
| `PORT` | `8080` | HTTP port |
| `FLEET_API_DB_POOL_SIZE` | `10` | Hikari pool size |

Docker (build context is the repo root): `docker build -f services/fleet-api/Dockerfile -t cohortex/fleet-api .`

## Tests

```bash
./gradlew :services:fleet-api:test                      # unit + integration (Docker needed for Testcontainers)
./gradlew :services:fleet-api:test -PskipIntegration     # unit tests only
./gradlew :services:fleet-api:test -PjavaToolchain=21    # on a machine with only JDK 21
```

| Test | Proves |
| --- | --- |
| `AfrMathTest` | FR-ANA-1: all 1,000 cases in `contracts/fixtures/afr_ci_cases.json` (SciPy) agree to 1e-9 relative |
| `ParamsTest` | FR-API-8 boundaries: 8 quarters OK / 9 rejected; size 500 OK / 501 rejected; limit, enums, SMART attrs |
| `CohortServiceTest` | compare ranking: min_drives filter, AFR descending, ties by model, limit, rate ratio |
| `FleetApiIT` | FR-API-1/2/3/4/5/6/8 truth on the hand-computed dataset in `src/test/resources/seed.sql`, problem-details shapes, FR-OPS-4 probes |
| `OpenApiContractIT` | FR-API-7: served `/v3/api-docs` (OpenAPI 3.1) contains every path and method in `contracts/openapi/fleet-api.yaml`, and the YAML covers every served `/v1` operation |

Integration tests (tag `integration`) start `pgvector/pgvector:0.8.7-pg18` with Testcontainers and
skip themselves when Docker is unavailable. Without Docker, point them at an empty database that has
pgvector installed: `COHORTEX_FLEET_TEST_JDBC_URL=jdbc:postgresql://localhost:5432/fleet_test`
(plus `COHORTEX_FLEET_TEST_DB_USER`, `COHORTEX_FLEET_TEST_DB_PASSWORD`).

## How it works

**Request path.** A controller parses and validates the parameters (`web/Params`), a service turns
SQL totals into answers (`api/CohortService`), and `store/FleetStore` holds every SQL statement. The
SQL is fixed text with bind parameters; no request value is ever spliced into a query (ADR-001).
Flyway creates the schema from `db/migrations` at startup; the API itself only reads.

**Where the numbers come from.** Ingest writes one `cohort_daily` row per model and day:
`drive_count` (drives reporting that day) and `failures` (drives whose last day it was). Summing
`drive_count` over days gives **drive-days**, the exposure. A 90-day quarter with 100 drives every
day is 9,000 drive-days.

**AFR.** Backblaze's annualized failure rate is failures per drive-year, in percent:

```
afr_pct = failures * 365 * 100 / drive_days
```

Example: 2 failures over 9,098 drive-days is 2 × 36,500 / 9,098 = 8.02 %. Think of it as "if you
ran 100 drives for a year at this rate, about 8 would fail".

**Why an interval.** Failures are rare, so the count is noisy. Model the failure count `k` as
Poisson with unknown mean `μ` (expected failures for this exposure). A small cohort with 1 failure
and a big one with 1,000 failures can have the same AFR, but we are far less sure about the first.
The 95% interval says which values of `μ` are consistent with seeing `k`.

**Exact Poisson (Garwood) interval.** For a 95% interval, `a = (1 − 0.95) / 2 = 0.025` in each tail.

```
lower count = chi2.ppf(a,     2k)     / 2      (0 when k = 0)
upper count = chi2.ppf(1 − a, 2k + 2) / 2
ci_low_pct  = lower count * 365 * 100 / drive_days   (same factor as AFR)
ci_high_pct = upper count * 365 * 100 / drive_days
```

Why chi-square? The Poisson CDF and the chi-square (gamma) CDF are tied by the identity
`P(Poisson(μ) ≥ k) = P(χ²(2k) ≤ 2μ)`. The upper bound is the `μ` at which seeing `k` or fewer
failures would happen only 2.5% of the time; the lower bound is the `μ` at which seeing `k` or more
would happen only 2.5% of the time. Solving those two equations with the identity gives the
chi-square quantiles above. "Exact" means it uses the Poisson distribution directly rather than a
normal approximation, so it stays honest for 0, 1 or 2 failures. With `k = 0` the lower bound is 0
and the upper count is `−ln(0.025) ≈ 3.69` failures: zero failures in 365 drive-days still allows an
AFR up to 369%.

In Java, `AfrMath` uses Apache Commons Statistics `ChiSquaredDistribution.inverseCumulativeProbability`
(the same function as SciPy's `chi2.ppf`). `afr_pct` multiplies the integers first and divides once,
which gives the same double as Python's `failures * 365 * 100 / drive_days`. `AfrMathTest` checks all
1,000 SciPy-generated cases in `contracts/fixtures/afr_ci_cases.json` to 1e-9 relative, which is how
FR-ANA-1 keeps Java and Python (mcp-stats) identical.

**Endpoint rules worth knowing** (implementation-notes §5).

- Windows `[from, to]` are inclusive. The rule counts calendar quarters touched, so 2024-07-01..2026-06-30
  is 8 quarters (OK) and 2024-04-01..2026-06-30 is 9 (400). A quarter clipped by the window only
  counts its days inside the window, but keeps the quarter's label.
- `compare`: a model qualifies when its drive count on its **last day inside the window** is at least
  `min_drives` (default 60), so a model that is being retired drops out. `rate_ratio_vs_fleet` is
  the model's AFR divided by the AFR of all models of the source in the window (qualifying or not);
  2.0 means "fails twice as often as the fleet". Ranked by AFR descending, ties by model name.
- `models.drive_count` is the count on the model's latest day in `cohort_daily`.
- `fleet/summary.drives` counts distinct drives whose `[first_seen, last_seen]` overlaps the window.
- `smart-trend` reads only the 1% hash-sampled drives (`drive.sampled`); `p50`/`p95` use
  `percentile_cont` (linear interpolation), `nonzero_share` is the share of drive-days with
  `raw_value > 0`, and `n_drives` is the sample size behind each point.
- `failed-drives`: `age_days = failed_on − first_seen`; `last_smart` holds the raw values recorded on
  the failure day.
