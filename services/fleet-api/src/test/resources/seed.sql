-- Hand-computed dataset for fleet-api integration tests. Truth is written out in FleetApiIT.
--
-- drive_model: 1 MODEL_A, 2 MODEL_B, 3 MODEL_C (backblaze, hdd); 4 MA1 (alibaba, ssd)
-- cohort_daily
--   MODEL_A 2026-01-01..2026-06-30: 100 drives/day, 98 on 2026-06-30; failures 1 on 02-10, 2 on 05-05
--           2026Q1 = 90 days * 100 = 9000 drive-days, 1 failure
--           2026Q2 = 90 * 100 + 98 = 9098 drive-days, 2 failures
--   MODEL_B 2026-04-01..2026-06-30: 200 drives/day; failures on 04-15 and 06-01 -> 18200, 2
--   MODEL_C 2026-04-01..2026-06-30: 10 drives/day; failure on 05-01            -> 910, 1
--   MA1     2018-01-01..2018-01-31: 50 drives/day, no failures                 -> 1550, 0

TRUNCATE alert, smart_daily, cohort_daily, drive, drive_model RESTART IDENTITY CASCADE;

INSERT INTO drive_model (id, source, model, media, capacity_bytes) VALUES
  (1, 'backblaze', 'MODEL_A', 'hdd', 12000138625024),
  (2, 'backblaze', 'MODEL_B', 'hdd', 16000900661248),
  (3, 'backblaze', 'MODEL_C', 'hdd', 8001563222016),
  (4, 'alibaba',   'MA1',     'ssd', NULL);

INSERT INTO cohort_daily (model_id, day, drive_count, failures)
SELECT 1, g::date,
       CASE WHEN g::date = DATE '2026-06-30' THEN 98 ELSE 100 END,
       CASE g::date WHEN DATE '2026-02-10' THEN 1 WHEN DATE '2026-05-05' THEN 2 ELSE 0 END
FROM generate_series(DATE '2026-01-01', DATE '2026-06-30', INTERVAL '1 day') AS g;

INSERT INTO cohort_daily (model_id, day, drive_count, failures)
SELECT 2, g::date, 200,
       CASE WHEN g::date IN (DATE '2026-04-15', DATE '2026-06-01') THEN 1 ELSE 0 END
FROM generate_series(DATE '2026-04-01', DATE '2026-06-30', INTERVAL '1 day') AS g;

INSERT INTO cohort_daily (model_id, day, drive_count, failures)
SELECT 3, g::date, 10, CASE WHEN g::date = DATE '2026-05-01' THEN 1 ELSE 0 END
FROM generate_series(DATE '2026-04-01', DATE '2026-06-30', INTERVAL '1 day') AS g;

INSERT INTO cohort_daily (model_id, day, drive_count, failures)
SELECT 4, g::date, 50, 0
FROM generate_series(DATE '2018-01-01', DATE '2018-01-31', INTERVAL '1 day') AS g;

-- drive: for fleet/summary (Q2 2026 overlap: A-2, A-3, A-4, B-1, B-2, C-1 = 6) and failed-drives.
INSERT INTO drive (source, drive_id, model_id, first_seen, last_seen, failed_on, sampled) VALUES
  ('backblaze', 'A-1',   1, DATE '2026-01-01', DATE '2026-02-10', DATE '2026-02-10', false),
  ('backblaze', 'A-2',   1, DATE '2026-01-01', DATE '2026-05-05', DATE '2026-05-05', true),
  ('backblaze', 'A-3',   1, DATE '2026-03-01', DATE '2026-05-05', DATE '2026-05-05', false),
  ('backblaze', 'A-4',   1, DATE '2026-01-01', DATE '2026-06-30', NULL,              true),
  ('backblaze', 'B-1',   2, DATE '2026-04-01', DATE '2026-04-15', DATE '2026-04-15', false),
  ('backblaze', 'B-2',   2, DATE '2025-10-01', DATE '2026-06-01', DATE '2026-06-01', false),
  ('backblaze', 'C-1',   3, DATE '2026-04-01', DATE '2026-05-01', DATE '2026-05-01', false),
  ('backblaze', 'OLD-1', 1, DATE '2025-01-01', DATE '2025-12-31', NULL,              false),
  ('alibaba',   'MA1:7', 4, DATE '2018-01-01', DATE '2018-01-31', NULL,              true);

-- smart_daily monthly partitions (named as ingest names them, implementation-notes §3).
CREATE TABLE IF NOT EXISTS smart_daily_y2026m02 PARTITION OF smart_daily
  FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
CREATE TABLE IF NOT EXISTS smart_daily_y2026m05 PARTITION OF smart_daily
  FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
CREATE TABLE IF NOT EXISTS smart_daily_y2026m06 PARTITION OF smart_daily
  FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');

-- Sampled drives A-2 and A-4 carry attr 5 in Q2: [10, 12, 0, 0, 4]
--   quarter 2026Q2: p50 4, p95 11.6, nonzero_share 0.6, n_drives 2
--   month 2026-05:  [10, 12, 0, 0] p50 5, p95 11.7, nonzero_share 0.5, n_drives 2
--   month 2026-06:  [4]            p50 4, p95 4,    nonzero_share 1.0, n_drives 1
-- A-3 is not sampled, so its attr 5 = 100 is excluded from trends but is its last SMART value.
INSERT INTO smart_daily (source, drive_id, day, attr, raw_value, normalized) VALUES
  ('backblaze', 'A-1', DATE '2026-02-10', 5,   0,   100),
  ('backblaze', 'A-2', DATE '2026-05-04', 5,   10,  100),
  ('backblaze', 'A-2', DATE '2026-05-05', 5,   12,  100),
  ('backblaze', 'A-2', DATE '2026-05-05', 197, 3,   100),
  ('backblaze', 'A-4', DATE '2026-05-04', 5,   0,   100),
  ('backblaze', 'A-4', DATE '2026-05-05', 5,   0,   100),
  ('backblaze', 'A-4', DATE '2026-06-30', 5,   4,   100),
  ('backblaze', 'A-3', DATE '2026-05-05', 5,   100, 90);

INSERT INTO alert (id, model_id, opened_at, window_start, window_end, baseline_afr, current_afr,
                   rate_ratio, p_value, status, resolved_at) VALUES
  ('00000000-0000-0000-0000-0000000000a1', 2, TIMESTAMPTZ '2026-07-01 00:00:00+00',
   DATE '2026-04-01', DATE '2026-06-30', 1.5, 4.01, 2.67, 0.01, 'open', NULL),
  ('00000000-0000-0000-0000-0000000000a2', 1, TIMESTAMPTZ '2026-04-01 12:00:00+00',
   DATE '2026-01-01', DATE '2026-03-31', 2.0, 4.06, 2.03, 0.04, 'resolved',
   TIMESTAMPTZ '2026-05-01 00:00:00+00');
