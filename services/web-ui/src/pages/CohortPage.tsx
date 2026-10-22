import { useId, useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { api } from '../api';
import type { Granularity, Source } from '../api/types';
import {
  AfrChart,
  AfrTable,
  ChartFigure,
  SmartPercentileChart,
  SmartShareChart,
  SmartTable,
} from '../components/charts';
import { EmptyState, ErrorNotice, SkeletonRows } from '../components/Feedback';
import { WindowControls } from '../components/WindowControls';
import { clampWindow, type WindowValue } from '../lib/window';
import { SOURCES, smartAttrLabel } from '../config';
import { formatInt } from '../lib/format';
import { listQuarters, shiftQuarter, windowDates } from '../lib/quarters';
import { buildPath, navigate, type Route } from '../router';
import { Link } from '../components/Link';

const PAGE_SIZE = 25;

function cohortWindow(source: Source, query: URLSearchParams): WindowValue {
  const info = SOURCES[source];
  // Default to the widest window the API accepts within the source's coverage.
  const all = listQuarters(info.first, info.last);
  const defaultFrom = all.length > 8 ? shiftQuarter(info.last, -7) : info.first;
  return clampWindow({
    source,
    from: query.get('from') ?? defaultFrom,
    to: query.get('to') ?? info.last,
  });
}

export function CohortPage({ route }: { route: Route }) {
  const rawSource = route.segments[1];
  const model = route.segments[2] ?? '';
  const source: Source = rawSource === 'alibaba' ? 'alibaba' : 'backblaze';
  const info = SOURCES[source];
  const win = cohortWindow(source, route.query);
  const dates = windowDates(win.from, win.to);
  const granularity: Granularity = route.query.get('granularity') === 'month' ? 'month' : 'quarter';
  const attrParam = Number(route.query.get('attr'));
  const attr = info.smartAttrs.includes(attrParam)
    ? attrParam
    : info.smartAttrs.includes(197)
      ? 197
      : 5;
  const [page, setPage] = useState(0);
  const ids = useId();

  const update = (changes: Record<string, string | number>) =>
    navigate(
      buildPath(['cohort', source, model], {
        from: win.from,
        to: win.to,
        granularity,
        attr,
        ...changes,
      }),
      { replace: true },
    );

  const afr = useQuery({
    queryKey: ['afr', source, model, dates.from, dates.to, granularity],
    queryFn: () => api.cohortAfr({ source, model, ...dates, granularity }),
    placeholderData: keepPreviousData,
  });
  const fleet = useQuery({
    queryKey: ['summary', source, dates.from, dates.to],
    queryFn: () => api.fleetSummary({ source, ...dates }),
  });
  const smart = useQuery({
    queryKey: ['smart', source, model, attr, dates.from, dates.to, granularity],
    queryFn: () => api.smartTrend({ source, model, attr, ...dates, granularity }),
    placeholderData: keepPreviousData,
  });
  const failed = useQuery({
    queryKey: ['failed', source, model, dates.from, dates.to, page],
    queryFn: () => api.failedDrives({ source, model, ...dates, page, size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });

  const investigateHref = buildPath(['investigate'], {
    q: `Did the failure rate of ${model} change between ${win.from} and ${win.to}, and what is driving it?`,
    source,
    models: model,
    from: dates.from,
    to: dates.to,
  });

  const smartKeys = failed.data?.items[0] ? Object.keys(failed.data.items[0].last_smart) : [];

  return (
    <div className="section-gap">
      <div>
        <nav className="breadcrumb" aria-label="Breadcrumb">
          <Link to={buildPath(['fleet'], { source })}>Fleet</Link>
          <span aria-hidden>/</span>
          <span aria-current="page">{model}</span>
        </nav>
        <div className="page-header" style={{ marginBottom: 0 }}>
          <div>
            <h1>{model}</h1>
            <p>
              {info.label} {info.media} cohort. Annualized failure rate with exact 95% intervals,
              SMART trends from the sampled drives, and the drives that failed.
            </p>
          </div>
          <Link to={investigateHref} className="button button-primary">
            Investigate this cohort
          </Link>
        </div>
      </div>

      <div className="controls">
        <WindowControls
          value={win}
          showSource={false}
          onChange={(next) => {
            setPage(0);
            update({ from: next.from, to: next.to });
          }}
        />
        <fieldset className="field" style={{ border: 'none', padding: 0, margin: 0 }}>
          <legend style={{ padding: 0, marginBottom: 6 }}>Granularity</legend>
          <div className="segmented">
            {(['quarter', 'month'] as const).map((g) => (
              <label key={g}>
                <input
                  type="radio"
                  name={`${ids}-granularity`}
                  checked={granularity === g}
                  onChange={() => update({ granularity: g })}
                />
                {g === 'quarter' ? 'Quarter' : 'Month'}
              </label>
            ))}
          </div>
        </fieldset>
      </div>

      <section className="panel" aria-labelledby={`${ids}-afr`}>
        <div className="panel-header">
          <h2 id={`${ids}-afr`}>Annualized failure rate</h2>
          <p>Points are AFR; whiskers are exact Poisson 95% intervals.</p>
        </div>
        {afr.isPending ? (
          <SkeletonRows rows={5} />
        ) : afr.isError ? (
          <div className="panel-pad">
            <ErrorNotice error={afr.error} />
          </div>
        ) : afr.data.series.length === 0 ? (
          <EmptyState title="No data in this window" />
        ) : (
          <ChartFigure
            caption={`AFR of ${model} by ${granularity} with 95% intervals`}
            legend={
              <>
                <span className="legend-item">
                  <span className="legend-swatch" /> AFR
                </span>
                <span className="legend-item">
                  <span className="legend-whisker" /> 95% interval
                </span>
                {fleet.data && (
                  <span className="legend-item">
                    <span className="legend-swatch dashed" /> {info.label} fleet AFR,{' '}
                    {fleet.data.afr_pct.toFixed(2)}%
                  </span>
                )}
              </>
            }
            table={<AfrTable series={afr.data.series} />}
          >
            <AfrChart series={afr.data.series} fleetAfr={fleet.data?.afr_pct ?? null} />
          </ChartFigure>
        )}
      </section>

      <section className="panel" aria-labelledby={`${ids}-smart`}>
        <div className="panel-header">
          <div>
            <h2 id={`${ids}-smart`}>SMART trend</h2>
            <p style={{ marginTop: 2 }}>
              Raw values from the 1% hash sample plus failed drives, not the full cohort.
            </p>
          </div>
          <label className="field" htmlFor={`${ids}-attr`}>
            Attribute
            <select
              id={`${ids}-attr`}
              className="select"
              value={attr}
              onChange={(e) => update({ attr: Number(e.target.value) })}
            >
              {info.smartAttrs.map((a) => (
                <option key={a} value={a}>
                  {smartAttrLabel(a)}
                </option>
              ))}
            </select>
          </label>
        </div>
        {smart.isPending ? (
          <SkeletonRows rows={4} />
        ) : smart.isError ? (
          <div className="panel-pad">
            <ErrorNotice error={smart.error} />
          </div>
        ) : smart.data.series.length === 0 ? (
          <EmptyState title="No SMART data in this window" />
        ) : (
          <div
            className="chart-grid"
            style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 0 }}
          >
            <ChartFigure
              caption={`${smartAttrLabel(attr)}: p50 and p95 by ${granularity}`}
              legend={
                <>
                  <span className="legend-item">
                    <span className="legend-swatch" style={{ background: 'var(--series-2)' }} /> p95
                  </span>
                  <span className="legend-item">
                    <span className="legend-swatch" /> p50
                  </span>
                </>
              }
              table={<SmartTable series={smart.data.series} />}
            >
              <SmartPercentileChart series={smart.data.series} />
            </ChartFigure>
            <ChartFigure
              caption={`${smartAttrLabel(attr)}: share of drive-days with a non-zero value`}
              legend={
                <span className="legend-item">
                  <span className="legend-swatch" style={{ height: 8, borderRadius: 2 }} /> Share of
                  drive-days above zero
                </span>
              }
            >
              <SmartShareChart series={smart.data.series} />
            </ChartFigure>
          </div>
        )}
      </section>

      <section className="panel" aria-labelledby={`${ids}-failed`}>
        <div className="panel-header">
          <h2 id={`${ids}-failed`}>Failed drives</h2>
          <p>Age at failure and SMART raw values on the last day.</p>
        </div>
        {failed.isPending ? (
          <SkeletonRows rows={5} />
        ) : failed.isError ? (
          <div className="panel-pad">
            <ErrorNotice error={failed.error} />
          </div>
        ) : failed.data.items.length === 0 ? (
          <EmptyState title="No failures in this window" />
        ) : (
          <>
            <div className="table-wrap">
              <table className="data" data-testid="failed-table">
                <thead>
                  <tr>
                    <th scope="col">Drive</th>
                    <th scope="col">Failed on</th>
                    <th scope="col" className="num">
                      Age (days)
                    </th>
                    <th scope="col">Last SMART values</th>
                  </tr>
                </thead>
                <tbody>
                  {failed.data.items.map((d) => (
                    <tr key={d.drive_id}>
                      <td className="mono">{d.drive_id}</td>
                      <td>{d.failed_on}</td>
                      <td className="num">{formatInt(d.age_days)}</td>
                      <td>
                        <span className="kv-chips">
                          {(smartKeys.length ? smartKeys : Object.keys(d.last_smart)).map((k) => (
                            <span key={k} className="kv-chip" title={smartAttrLabel(Number(k))}>
                              {k}
                              <b>{d.last_smart[k] ?? '–'}</b>
                            </span>
                          ))}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="pager">
              <span>
                {formatInt(failed.data.page * failed.data.size + 1)} to{' '}
                {formatInt(Math.min(failed.data.total, (failed.data.page + 1) * failed.data.size))}{' '}
                of {formatInt(failed.data.total)}
              </span>
              <div className="pager-buttons">
                <button
                  type="button"
                  className="button button-small"
                  disabled={page === 0}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                >
                  Previous
                </button>
                <button
                  type="button"
                  className="button button-small"
                  disabled={(page + 1) * PAGE_SIZE >= failed.data.total}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                </button>
              </div>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
