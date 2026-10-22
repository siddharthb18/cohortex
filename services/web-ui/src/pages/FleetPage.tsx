import { useMemo, useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { api } from '../api';
import type { CohortCompareRow } from '../api/types';
import { EmptyState, ErrorNotice, SkeletonRows } from '../components/Feedback';
import { SortHeader } from '../components/SortHeader';
import { WindowControls } from '../components/WindowControls';
import { windowFromQuery, type WindowValue } from '../lib/window';
import { DEFAULT_MIN_DRIVES, SOURCES } from '../config';
import { formatCompact, formatInt, formatPct, formatRatio } from '../lib/format';
import { windowDates } from '../lib/quarters';
import { nextSort, sortRows, type SortState } from '../lib/sort';
import { buildPath, navigate, type Route } from '../router';
import { Link } from '../components/Link';

type Column = 'model' | 'drive_days' | 'failures' | 'afr_pct' | 'rate_ratio_vs_fleet';

function CiBar({
  row,
  max,
  fleetAfr,
}: {
  row: CohortCompareRow;
  max: number;
  fleetAfr: number | null;
}) {
  const scale = (v: number) => `${Math.min(100, (v / max) * 100)}%`;
  return (
    <span className="ci-track" aria-hidden>
      {fleetAfr !== null && <span className="ci-fleet" style={{ left: scale(fleetAfr) }} />}
      <span
        className="ci-range"
        style={{
          left: scale(row.ci_low_pct),
          width: `calc(${scale(row.ci_high_pct)} - ${scale(row.ci_low_pct)})`,
        }}
      />
      <span className="ci-point" style={{ left: scale(row.afr_pct) }} />
    </span>
  );
}

export function FleetPage({ route }: { route: Route }) {
  const win = windowFromQuery(route.query);
  const dates = windowDates(win.from, win.to);
  const [sort, setSort] = useState<SortState<Column>>({ key: 'afr_pct', dir: 'desc' });

  const setWindow = (next: WindowValue) =>
    navigate(buildPath(['fleet'], { source: next.source, from: next.from, to: next.to }), {
      replace: true,
    });

  const compare = useQuery({
    queryKey: ['compare', win.source, dates.from, dates.to],
    queryFn: () =>
      api.compareCohorts({
        ...dates,
        source: win.source,
        minDrives: DEFAULT_MIN_DRIVES,
        limit: 50,
      }),
    placeholderData: keepPreviousData,
  });
  const summary = useQuery({
    queryKey: ['summary', win.source, dates.from, dates.to],
    queryFn: () => api.fleetSummary({ ...dates, source: win.source }),
    placeholderData: keepPreviousData,
  });

  const rows = useMemo(
    () => (compare.data ? sortRows(compare.data, sort.key, sort.dir) : []),
    [compare.data, sort],
  );
  const maxCi = useMemo(
    () => Math.max(0.5, ...(compare.data ?? []).map((r) => r.ci_high_pct)),
    [compare.data],
  );
  const fleetAfr = summary.data?.afr_pct ?? null;
  const windowLabel = win.from === win.to ? win.from : `${win.from} to ${win.to}`;

  const onSort = (column: Column) =>
    setSort((s) => nextSort(s, column, column === 'model' ? 'asc' : 'desc'));

  return (
    <div className="section-gap">
      <div className="page-header">
        <div>
          <h1>Fleet</h1>
          <p>
            Annualized failure rate by drive model, with exact 95% Poisson intervals and each
            cohort's rate relative to the whole {SOURCES[win.source].label} fleet.
          </p>
        </div>
        <WindowControls value={win} onChange={setWindow} />
      </div>

      <section className="panel" aria-label="Fleet summary">
        {summary.isError ? (
          <div className="panel-pad">
            <ErrorNotice error={summary.error} title="Could not load the fleet summary." />
          </div>
        ) : (
          <div className="stat-strip" data-testid="fleet-summary">
            <div className="stat">
              <div className="stat-label">Drives</div>
              <div className="stat-value tabular">
                {summary.data ? formatInt(summary.data.drives) : '–'}
              </div>
              <div className="stat-sub">{windowLabel}</div>
            </div>
            <div className="stat">
              <div className="stat-label">Drive-days</div>
              <div className="stat-value tabular">
                {summary.data ? formatCompact(summary.data.drive_days) : '–'}
              </div>
              <div className="stat-sub">
                {summary.data ? formatInt(summary.data.drive_days) : ''}
              </div>
            </div>
            <div className="stat">
              <div className="stat-label">Failures</div>
              <div className="stat-value tabular">
                {summary.data ? formatInt(summary.data.failures) : '–'}
              </div>
              <div className="stat-sub">
                {SOURCES[win.source].label} {SOURCES[win.source].media}
              </div>
            </div>
            <div className="stat">
              <div className="stat-label">Fleet AFR</div>
              <div className="stat-value tabular">
                {summary.data ? formatPct(summary.data.afr_pct) : '–'}
              </div>
              <div className="stat-sub">
                {summary.data
                  ? `95% CI ${summary.data.ci_low_pct.toFixed(2)} to ${summary.data.ci_high_pct.toFixed(2)}`
                  : ''}
              </div>
            </div>
          </div>
        )}
      </section>

      <section className="panel" aria-labelledby="cohorts-title">
        <div className="panel-header">
          <h2 id="cohorts-title">Cohorts</h2>
          <p>
            Models with at least {DEFAULT_MIN_DRIVES} drives on their last day in the window. Select
            a column to sort.
          </p>
        </div>
        {compare.isPending ? (
          <SkeletonRows rows={6} />
        ) : compare.isError ? (
          <div className="panel-pad">
            <ErrorNotice error={compare.error} title="Could not load cohorts." />
          </div>
        ) : rows.length === 0 ? (
          <EmptyState title="No cohorts in this window">
            No model had at least {DEFAULT_MIN_DRIVES} drives in {windowLabel}. Try another window
            or source.
          </EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="data" data-testid="cohort-table">
              <caption className="sr-only">
                Cohorts ranked by annualized failure rate, {windowLabel}
              </caption>
              <thead>
                <tr>
                  <SortHeader label="Model" column="model" sort={sort} onSort={onSort} />
                  <SortHeader
                    label="Drive-days"
                    column="drive_days"
                    sort={sort}
                    onSort={onSort}
                    numeric
                  />
                  <SortHeader
                    label="Failures"
                    column="failures"
                    sort={sort}
                    onSort={onSort}
                    numeric
                  />
                  <SortHeader label="AFR" column="afr_pct" sort={sort} onSort={onSort} numeric />
                  <th scope="col" className="num">
                    95% CI
                  </th>
                  <SortHeader
                    label="Rate ratio vs fleet"
                    column="rate_ratio_vs_fleet"
                    sort={sort}
                    onSort={onSort}
                    numeric
                  />
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.model}>
                    <td>
                      <Link
                        className="model-link"
                        to={buildPath(['cohort', win.source, row.model], {
                          from: win.from,
                          to: win.to,
                        })}
                      >
                        {row.model}
                      </Link>
                    </td>
                    <td className="num">{formatInt(row.drive_days)}</td>
                    <td className="num">{formatInt(row.failures)}</td>
                    <td className="num" data-testid="afr-cell">
                      <strong>{formatPct(row.afr_pct)}</strong>
                    </td>
                    <td className="num">
                      <span className="ci-cell">
                        <CiBar row={row} max={maxCi} fleetAfr={fleetAfr} />
                        <span>
                          {row.ci_low_pct.toFixed(2)} to {row.ci_high_pct.toFixed(2)}
                        </span>
                      </span>
                    </td>
                    <td className="num">{formatRatio(row.rate_ratio_vs_fleet)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
