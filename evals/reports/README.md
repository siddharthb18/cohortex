# Eval reports

`cohortex-eval run` writes `<UTC timestamp>-<mode>.json` (every graded case, raw run records,
metrics, gate result) and a Markdown summary with the same stem. Nightly and release summaries
(Markdown) are committed by CI; the JSON files are CI artifacts. `cohortex-eval gate` reads the
latest JSON here unless `--run` is given.
