-- Raw-layer views (DuckDB). Contract shared by ingest-batch (reconciliation) and the eval harness
-- (truth SQL). ADR-004: eval truth is computed only from these views over Parquet, never from Postgres.
--
-- `{raw}` is replaced with RAW_DATA_URI (a local directory or object-store URI) before execution.
-- Layout written by ingest-batch:
--   {raw}/backblaze/year=YYYY/quarter=Qn/YYYY-MM-DD.parquet   one file per day, all source columns lower-cased,
--                                                              plus schema_version (text)
--   {raw}/alibaba/smart/year=YYYY/month=MM/YYYYMMDD.parquet     one file per sampling day, all source columns,
--                                                              plus source_file_date (date)
--   {raw}/alibaba/failure_label.parquet                       model, disk_id, failure_time
-- Statements are plain DuckDB SQL separated by semicolons. When a source has no files yet, the loader
-- (cohortex_ingest.rawlayer / cohortex_evals.truth) replaces that source's read_parquet() views with
-- empty views of the same columns, so drive_day always exists.

CREATE OR REPLACE VIEW raw_backblaze_day AS
SELECT * FROM read_parquet('{raw}/backblaze/*/*/*.parquet', hive_partitioning = true, union_by_name = true);

CREATE OR REPLACE VIEW raw_alibaba_day AS
SELECT * FROM read_parquet('{raw}/alibaba/smart/*/*/*.parquet', hive_partitioning = true, union_by_name = true);

CREATE OR REPLACE VIEW raw_alibaba_failure AS
SELECT model, CAST(disk_id AS VARCHAR) AS disk_id, CAST(failure_time AS TIMESTAMP) AS failure_time
FROM read_parquet('{raw}/alibaba/failure_label.parquet');

-- Alibaba failure convention (docs/implementation-notes.md §3): failed_on is the drive's last observed
-- day on or before the label's failure date; failure = 1 on that day only, mirroring Backblaze.
CREATE OR REPLACE VIEW alibaba_failed_on AS
SELECT d.model, CAST(d.disk_id AS VARCHAR) AS disk_id, MAX(d.source_file_date) AS failed_on
FROM raw_alibaba_day d
JOIN raw_alibaba_failure f ON f.model = d.model AND f.disk_id = CAST(d.disk_id AS VARCHAR)
WHERE d.source_file_date <= CAST(f.failure_time AS DATE)
GROUP BY 1, 2;

-- Unified view; every truth SQL query starts here.
CREATE OR REPLACE VIEW drive_day AS
SELECT 'backblaze'               AS source,
       CAST(date AS DATE)        AS day,
       CAST(serial_number AS VARCHAR) AS drive_id,
       CAST(model AS VARCHAR)    AS model,
       CAST(capacity_bytes AS BIGINT) AS capacity_bytes,
       'hdd'                     AS media,
       CAST(failure AS INTEGER)  AS failure
FROM raw_backblaze_day
UNION ALL
SELECT 'alibaba'                 AS source,
       d.source_file_date        AS day,
       d.model || ':' || CAST(d.disk_id AS VARCHAR) AS drive_id,
       d.model                   AS model,
       CAST(NULL AS BIGINT)      AS capacity_bytes,
       'ssd'                     AS media,
       CASE WHEN fo.failed_on = d.source_file_date THEN 1 ELSE 0 END AS failure
FROM raw_alibaba_day d
LEFT JOIN alibaba_failed_on fo ON fo.model = d.model AND fo.disk_id = CAST(d.disk_id AS VARCHAR);
