# Fixtures

Small subsets of the public datasets for local development and CI (WP-01). Raw datasets are never
committed. `make seed` (`cohortex-ingest seed`) loads everything here end to end: raw layer under
`RAW_DATA_URI`, then the Postgres serving tables, then reconciliation.

## Current contents: SYNTHETIC data

> **The committed fixture is SYNTHETIC.** It has the exact file formats of the real sources but
> the values are generated. It is not Backblaze or Alibaba telemetry and no conclusion about real
> drives may be drawn from it. Model names start with `SYN-` (Backblaze) to make that visible.

The build sandbox cannot reach Backblaze or Tianchi (open questions 11 and 12), so a real subset
could not be built yet. Each folder holds a `fixture.json` with `"synthetic": true` and the seed.

| Folder | Format | Contents |
| --- | --- | --- |
| `backblaze/2026Q2/` | 91 × `YYYY-MM-DD.csv.gz`, Backblaze Drive Stats columns | 5 models, 360 drives, 31,494 drive-days, 12 failures, 2 drives in the 1% md5 sample. `SYN-ST16000` has a clear AFR step change: 0 failures in April, 3 in May, 4 in June |
| `alibaba/` | 30 × `YYYYMMDD.csv` + `ssd_failure_label.csv`, Tianchi columns | 6 models (MA1, MA2, MB1, MB2, MC1, MC2), 8 drives each, 6 failures; 2018-03-17 to 2018-04-15 (crosses 2018Q1 → 2018Q2) |

Regenerate (deterministic: same seed, same bytes):

```bash
uv run cohortex-ingest synthetic --out data/fixtures/backblaze/2026Q2 --quarter 2026Q2 --seed 42 --gzip
uv run cohortex-ingest synthetic --source alibaba --out data/fixtures/alibaba --seed 42
```

## Replacing it with a real subset (needs Siddharth's approval of the fixture choice, WP-01)

On a machine that can reach Backblaze:

```bash
uv run cohortex-ingest download --quarter 2026Q2                     # data/downloads/data_Q2_2026.zip
uv run cohortex-ingest build-fixture --zip data/downloads/data_Q2_2026.zip \
    --models "ST12000NM0008,HGST HUH721212ALE604,TOSHIBA MG08ACA16TA" \
    --sample 0.01 --out data/fixtures/backblaze
```

`build-fixture` keeps the chosen models only and, within them, the drives with
`int(md5(serial_number)[:8], 16) % 100 < round(sample * 100)` (with 0.01 that is exactly the
serving-layer 1% sample) plus every drive of those models that failed in the quarter. It writes
`<out>/<YYYYQn>/YYYY-MM-DD.csv.gz` with the published header and values, and a `fixture.json`
recording the ZIP's SHA-256, the models and the rule. Delete the synthetic quarter folder first if
the real quarter differs, keep the total under 3 MB (no file over 5 MB), update the table above
and the tests that assert synthetic content (`pipelines/ingest-batch/tests/test_seed_and_fixture.py`).

## Attribution

- Backblaze Drive Stats: courtesy of Backblaze; free, may not be sold. Cite Backblaze as the source.
- Alibaba SSD SMART logs: cite *General Feature Selection for Failure Prediction in Large-scale SSD
  Deployment* (Xu et al., DSN 2021).
