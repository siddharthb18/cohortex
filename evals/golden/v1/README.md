# Golden set v1 (draft)

30 drafted cases over Backblaze quarters 2025Q3–2026Q2 and Alibaba 2018–2019, in the shares of
[evaluation spec §2](/docs/specs/evaluation.md#2-golden-set-format-and-graders):

| Category | Cases | Truth |
| --- | --- | --- |
| lookup | 6 | `afr_pct`, `failures` or `drive_days` of one model or the fleet |
| compare | 6 | top model and its `afr_pct` (qualification per implementation-notes §5) |
| trend | 5 | `rate_ratio` later ÷ earlier; also both AFRs, direction and exact p-value |
| diagnostic | 4 | `truth_set` of models explaining ≥ 50% of the fleet change |
| ssd | 3 | top Alibaba model and its `afr_pct` |
| literature | 2 | `relevant_passages` (labeled in WP-10) |
| out_of_scope | 2 | must refuse |
| adversarial | 2 | canary absent / safe status |

Every case was drafted by an agent and has `"reviewed_by": null`, so **none of them is in the CI
gate yet**. `truth` is `null` until `make truth` runs over the real raw layer.

## How to review a case (Siddharth only)

Reviewing is human-owned (build plan §2: "a case enters the gate only after Siddharth runs the SQL
himself, checks the answer makes sense, and sets `reviewed_by`").

1. **Load the raw layer** for the periods the case uses (ingest-batch writes Parquet under
   `RAW_DATA_URI`, default `./data/raw`).
2. **Run the SQL yourself.** Either print the harness result for one case:

   ```bash
   uv run cohortex-eval truth --only compare-0001 --dry-run
   ```

   or paste `truth_sql` into any DuckDB session after creating the views from
   `contracts/rawlayer/views.sql` (replace `{raw}` with your raw-layer path). Read the SQL: does it
   answer exactly the question as worded (period bounds, source, thresholds, ratio direction)?
3. **Check the answer makes sense** using the case's `notes`: compare with Backblaze's published
   quarterly Drive Stats tables (small differences are expected; see the notes), check cohort sizes
   (`drive_days / days in period` ≈ drive count), that failures are not tiny (a compare winner with
   one failure on a small cohort is a bad question), and for trends that both quarters have failures.
   For diagnostic cases, check the direction of the fleet change and that `truth_set` is plausible.
4. **Fix if needed**: reword the question, adjust the SQL or tolerance, or drop the case. Run
   `uv run cohortex-eval validate` afterwards.
5. **Sign off**: set `"reviewed_by": "siddharth"` on that line, then run `make truth` so the stored
   `truth` and `snapshot_id` match the reviewed SQL. Commit the reviewed cases in their own PR.

Literature cases additionally need `relevant_passages` labeled once the corpus exists (WP-10).
Adversarial cases need a manual look at the trace to confirm no tool call carried SQL text or a
planted instruction.

A golden-set version change (`v2`) resets the regression baseline in a dedicated PR.
