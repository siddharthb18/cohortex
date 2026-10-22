# C1 ingest-batch

Download Backblaze and Alibaba data, convert to the Parquet raw layer, bulk-load serving tables, reconcile.

- **Built in:** WP-01, WP-02, WP-03, WP-09 (FR-ING-6) (see [build plan](/docs/specs/build-plan.md))
- **Covers:** FR-ING-1..6, FR-OPS-5 (`make seed`)
- **Contracts:** [contracts §1–2](/docs/specs/contracts.md), [raw-layer views](/contracts/rawlayer/views.sql),
  [implementation notes §2–3](/docs/implementation-notes.md)

## Commands

```bash
uv run cohortex-ingest seed                                # committed fixture → raw layer → Postgres
uv run cohortex-ingest backfill --quarter 2026Q2           # download → convert → load → reconcile
uv run cohortex-ingest backfill --quarter 2026Q2 --zip data/downloads/data_Q2_2026.zip
uv run cohortex-ingest download --quarter 2026Q2 [--dest data/downloads] [--sha256 HEX]
uv run cohortex-ingest convert --quarter 2026Q2 --src data/downloads/data_Q2_2026.zip
uv run cohortex-ingest load [--quarter 2026Q2 ...] [--source backblaze|alibaba]
uv run cohortex-ingest reconcile --quarter 2026Q2 [--source backblaze|alibaba]
uv run cohortex-ingest alibaba --src path/to/tianchi
uv run cohortex-ingest synthetic --out DIR --quarter 2026Q2 --seed 42 [--gzip] [--zip]
uv run cohortex-ingest synthetic --source alibaba --out DIR --seed 42
uv run cohortex-ingest build-fixture --zip data_Q2_2026.zip --models M1,M2,M3 --sample 0.01
uv run cohortex-ingest migrate                             # apply V1 if Flyway has not run
```

Settings (environment): `DATABASE_URL` (required for anything touching Postgres), `RAW_DATA_URI`
(default `./data/raw`), `EMBEDDING_DIM` (384, fills the V1 placeholder), `COHORTEX_WINDOW_QUARTERS`
(6). Each command prints a JSON summary on stdout and JSON-line logs on stderr. Exit code 0 is
success, 1 a failed run (unknown column, row-count or reconciliation mismatch, bad download), 2 a
configuration error.

## How it works

Two layers, on purpose (ADR-004). The **raw layer** keeps every source row as Parquet and is read
only by DuckDB; it is the truth the eval harness grades against. The **serving layer** is a few
small Postgres tables shaped for the APIs. Because they are built separately and then compared,
reconciliation is a real check, not the system grading itself.

One quarter flows like this (`pipeline.ingest_backblaze_quarter`):

1. **Download** (`download.py`, FR-ING-1). Stream `data_Qn_YYYY.zip` with httpx into a `.part`
   file while hashing it; check the HTTP status, the byte count against `Content-Length`, an
   optional expected SHA-256, and every ZIP member's CRC; then rename. An `ingest_run` row
   (`running`) records the URL, bytes and SHA-256 before anything else happens, in its own
   transaction, so a failed run still leaves a `failed` row behind.
2. **Validate** (`schema.py`, FR-ING-3). Each day file's header is lower-cased and checked: the
   11 known non-SMART columns are allowed, anything else must match `smart_<id>_(normalized|raw)`,
   or the run fails naming the column. `schema_version` = first 12 hex of SHA-256 of the
   lower-cased header line.
3. **Convert** (`convert.py`, FR-ING-2). ZIP members are extracted one at a time (a quarter is
   ~12 GB unzipped) and DuckDB copies each CSV to `{raw}/backblaze/year=YYYY/quarter=Qn/
   YYYY-MM-DD.parquet` with explicit column types and a `schema_version` column. The CSV's rows
   are counted independently (non-blank lines minus the header) and must equal the Parquet
   footer's row count. The quarter is written to `{raw}/.staging/` and swapped in only when every
   day passed, so a failure never leaves half a quarter.
4. **Derive and load** (`derive_load.py`, FR-ING-4). `rawlayer.connect()` defines the shared views
   from `contracts/rawlayer/views.sql` (empty stand-ins when a source has no files, so
   `drive_day` always exists). DuckDB derives `drive_model`, `drive`, `cohort_daily` and
   `smart_daily` from `drive_day` and writes CSVs that psycopg streams into Postgres with `COPY`,
   all inside **one transaction per quarter**: upsert models; delete and re-insert the quarter's
   `cohort_daily` and `smart_daily` rows; upsert `drive` with `least(first_seen)`,
   `greatest(last_seen)`, `coalesce(new failed_on, old)`. Running it twice changes nothing.
5. **Reconcile** (`reconcile.py`, FR-ING-5). Per model, drive-days and failures from `drive_day`
   must equal the sums of `cohort_daily` for the quarter. The JSON goes into
   `ingest_run.reconciliation`; a mismatch marks the run `failed` and exits 1.

`smart_daily` keeps the 13 contract attributes for (a) drives in the fixed 1% sample
(`int(md5(drive_id)[:8], 16) % 100 == 0`, implemented identically in Python and DuckDB) on every
observed day and (b) failed drives on the 60 days up to and including `failed_on`. A quarter's
load owns exactly its own days; to keep the 60-day window complete whatever order quarters are
loaded in, it also looks ahead 59 days in the raw layer for failures and adds (without
overwriting) the 59 days before the quarter for drives failing in it. Monthly partitions
`smart_daily_yYYYYmMM` are created just before loading.

**Alibaba** (`alibaba.py`, FR-ING-6) reuses the same machinery: `YYYYMMDD.csv` files become
`{raw}/alibaba/smart/year=YYYY/month=MM/YYYYMMDD.parquet` (+ `source_file_date`), the label file
becomes `{raw}/alibaba/failure_label.parquet`, and each calendar quarter is loaded and reconciled
with `source = 'alibaba'`. `drive_id` is `model:disk_id` (disk ids repeat across models) and the
failure day comes from the views: the drive's last observed day on or before the label date.

**`seed`** (FR-OPS-5) runs the same pipeline over `data/fixtures/` (folders instead of ZIPs; the
recorded SHA-256 is over a manifest of `path<TAB>sha256` lines). The committed fixture is
**synthetic** for now, see [data/fixtures/README.md](/data/fixtures/README.md).

## Decisions made here (simplest sound option; listed for Siddharth)

- The Backblaze schema file (`Drive_Stats_Schema_Current.csv`) is not fetched: the known-column list
  from implementation-notes §3 is the check (the sandbox cannot reach Backblaze; open question 12).
- Column types: `date` DATE, `capacity_bytes` BIGINT, `failure` INTEGER, all SMART columns
  DOUBLE; the other non-SMART columns (`datacenter`, `cluster_id`, ...) and Alibaba `disk_id`/`ds`
  are kept as text until their formats are verified (open question 2).
- Alibaba files are validated like Backblaze ones: `disk_id, ds, model` plus `n_<id>`/`r_<id>`,
  anything else fails naming the column.
- `ingest_run.schema_version` is the comma-separated list of distinct day versions (usually one).
- `ingest_run` is an append-only log: re-running `seed` adds rows; serving tables do not change.
- `drive_model.capacity_bytes` is the mode over the loaded quarter (ties → smaller value); a later
  load overwrites it. `drive.model_id` follows the drive's latest observed model.
- Within a quarter, `failed_on` is the first `failure = 1` day if a drive has several; across
  quarters `coalesce(new, old)` applies as specified.
- `smart_daily` skips an attribute on a day when both raw and normalized are empty; `normalized`
  is rounded to `smallint` and set NULL if out of range.
- The md5 sample hashes `drive.drive_id` (for Alibaba, `model:disk_id`).
- `load` without `--quarter` loads the latest `COHORTEX_WINDOW_QUARTERS` Backblaze quarters found in
  the raw layer; it never deletes older serving data.
- Writing the raw layer needs a local `RAW_DATA_URI`; object-store URIs work for reading only.
- Python applies V1 only when neither `flyway_schema_history` nor `ingest_run` exists.

## Tests

`uv run pytest pipelines/ingest-batch`: each FR acceptance test is named in its module docstring
(`test_download.py` FR-ING-1, `test_convert.py` FR-ING-2, `test_schema.py` FR-ING-3,
`test_load.py` FR-ING-4, `test_reconcile.py` FR-ING-5, `test_alibaba.py` FR-ING-6,
`test_seed_and_fixture.py` FR-OPS-5). Integration tests use a real Postgres: the session creates
`cohortex_test_ingest_<random>` from `COHORTEX_TEST_DATABASE_URL`, applies V1 and drops it.
Downloads use an httpx `MockTransport`; no test touches the network.
