import type { ReactNode } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  ErrorBar,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { AfrPoint, SmartTrendPoint } from '../api/types';
import { formatCompact, formatInt, formatPct } from '../lib/format';

// Chart chrome reads the same CSS tokens as the page, so light and dark both work.
const AXIS_TICK = { fill: 'var(--ink-3)', fontSize: 12 };
const AXIS_LINE = { stroke: 'var(--chart-axis)' };
const GRID = 'var(--chart-grid)';

interface TooltipShape {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: unknown }>;
}

function TooltipBox({ title, rows }: { title: string; rows: [string, string][] }) {
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-title">{title}</div>
      <dl>
        {rows.map(([k, v]) => (
          <div key={k} style={{ display: 'contents' }}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function ChartFigure({
  caption,
  legend,
  children,
  table,
}: {
  caption: string;
  legend?: ReactNode;
  children: ReactNode;
  table?: ReactNode;
}) {
  return (
    <figure style={{ margin: 0 }}>
      <figcaption className="sr-only">{caption}</figcaption>
      {legend && (
        <div className="chart-legend" style={{ padding: '14px 24px 0' }} aria-hidden>
          {legend}
        </div>
      )}
      <div className="chart-box">{children}</div>
      {table && (
        <details className="table-toggle">
          <summary>Show data table</summary>
          <div className="table-wrap">{table}</div>
        </details>
      )}
    </figure>
  );
}

interface AfrDatum extends AfrPoint {
  err: [number, number];
}

/** AFR over time with exact 95% interval whiskers and an optional fleet reference line (FR-UI-2). */
export function AfrChart({ series, fleetAfr }: { series: AfrPoint[]; fleetAfr: number | null }) {
  const data: AfrDatum[] = series.map((p) => ({
    ...p,
    err: [p.afr_pct - p.ci_low_pct, p.ci_high_pct - p.afr_pct],
  }));
  const max = Math.max(fleetAfr ?? 0, ...series.map((p) => p.ci_high_pct), 0.5);
  const top = Math.ceil(max * 1.1 * 2) / 2;

  return (
    <div data-testid="afr-chart" style={{ width: '100%', height: 300 }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 12, right: 24, bottom: 4, left: 4 }}>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis
            dataKey="period"
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={AXIS_LINE}
            minTickGap={12}
          />
          <YAxis
            domain={[0, top]}
            tickFormatter={(v: number) => `${v}%`}
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={false}
            width={52}
          />
          <Tooltip
            cursor={{ stroke: 'var(--line-strong)' }}
            isAnimationActive={false}
            content={(props: TooltipShape) => {
              const d = props.payload?.[0]?.payload as AfrDatum | undefined;
              if (!props.active || !d) return null;
              return (
                <TooltipBox
                  title={d.period}
                  rows={[
                    ['AFR', formatPct(d.afr_pct)],
                    ['95% CI', `${d.ci_low_pct.toFixed(2)} to ${d.ci_high_pct.toFixed(2)}`],
                    ['Failures', formatInt(d.failures)],
                    ['Drive-days', formatInt(d.drive_days)],
                  ]}
                />
              );
            }}
          />
          {fleetAfr !== null && (
            <ReferenceLine
              y={fleetAfr}
              stroke="var(--chart-ref)"
              strokeDasharray="4 4"
              strokeWidth={1.5}
              ifOverflow="extendDomain"
            />
          )}
          <Line
            type="linear"
            dataKey="afr_pct"
            name="AFR"
            stroke="var(--series-1)"
            strokeWidth={2}
            dot={{ r: 4, fill: 'var(--series-1)', stroke: 'var(--surface)', strokeWidth: 2 }}
            activeDot={{ r: 6, fill: 'var(--series-1)', stroke: 'var(--surface)', strokeWidth: 2 }}
            isAnimationActive={false}
          >
            <ErrorBar
              dataKey="err"
              width={8}
              strokeWidth={1.5}
              stroke="var(--series-1)"
              direction="y"
            />
          </Line>
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function AfrTable({ series }: { series: AfrPoint[] }) {
  return (
    <table className="data">
      <thead>
        <tr>
          <th scope="col">Period</th>
          <th scope="col" className="num">
            Drive-days
          </th>
          <th scope="col" className="num">
            Failures
          </th>
          <th scope="col" className="num">
            AFR
          </th>
          <th scope="col" className="num">
            95% CI
          </th>
        </tr>
      </thead>
      <tbody>
        {series.map((p) => (
          <tr key={p.period}>
            <td>{p.period}</td>
            <td className="num">{formatInt(p.drive_days)}</td>
            <td className="num">{formatInt(p.failures)}</td>
            <td className="num">{formatPct(p.afr_pct)}</td>
            <td className="num">
              {p.ci_low_pct.toFixed(2)} to {p.ci_high_pct.toFixed(2)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function formatSmart(v: number | null): string {
  if (v === null) return '–';
  return Math.abs(v) >= 10000 ? formatCompact(v) : formatInt(Math.round(v * 10) / 10);
}

/** p50 and p95 of one SMART attribute over time (FR-UI-3). */
export function SmartPercentileChart({ series }: { series: SmartTrendPoint[] }) {
  return (
    <div data-testid="smart-chart" style={{ width: '100%', height: 240 }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={series} margin={{ top: 12, right: 24, bottom: 4, left: 4 }}>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis
            dataKey="period"
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={AXIS_LINE}
            minTickGap={12}
          />
          <YAxis
            tickFormatter={(v: number) => formatSmart(v)}
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={false}
            width={52}
          />
          <Tooltip
            cursor={{ stroke: 'var(--line-strong)' }}
            isAnimationActive={false}
            content={(props: TooltipShape) => {
              const d = props.payload?.[0]?.payload as SmartTrendPoint | undefined;
              if (!props.active || !d) return null;
              return (
                <TooltipBox
                  title={d.period}
                  rows={[
                    ['p95', formatSmart(d.p95)],
                    ['p50', formatSmart(d.p50)],
                    ['Sampled drives', formatInt(d.n_drives)],
                  ]}
                />
              );
            }}
          />
          <Line
            type="linear"
            dataKey="p95"
            name="p95"
            stroke="var(--series-2)"
            strokeWidth={2}
            dot={{ r: 3, fill: 'var(--series-2)', stroke: 'var(--surface)', strokeWidth: 1.5 }}
            isAnimationActive={false}
            connectNulls
          />
          <Line
            type="linear"
            dataKey="p50"
            name="p50"
            stroke="var(--series-1)"
            strokeWidth={2}
            dot={{ r: 3, fill: 'var(--series-1)', stroke: 'var(--surface)', strokeWidth: 1.5 }}
            isAnimationActive={false}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Share of sampled drive-days with a non-zero raw value. */
export function SmartShareChart({ series }: { series: SmartTrendPoint[] }) {
  const data = series.map((p) => ({
    ...p,
    share_pct: p.nonzero_share === null ? null : p.nonzero_share * 100,
  }));
  return (
    <div style={{ width: '100%', height: 240 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 12, right: 24, bottom: 4, left: 4 }}>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis
            dataKey="period"
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={AXIS_LINE}
            minTickGap={12}
          />
          <YAxis
            tickFormatter={(v: number) => `${v}%`}
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={false}
            width={52}
          />
          <Tooltip
            cursor={{ fill: 'var(--surface-2)' }}
            isAnimationActive={false}
            content={(props: TooltipShape) => {
              const d = props.payload?.[0]?.payload as
                (SmartTrendPoint & { share_pct: number | null }) | undefined;
              if (!props.active || !d) return null;
              return (
                <TooltipBox
                  title={d.period}
                  rows={[
                    ['Non-zero share', d.share_pct === null ? '–' : formatPct(d.share_pct, 1)],
                    ['Sampled drives', formatInt(d.n_drives)],
                  ]}
                />
              );
            }}
          />
          <Bar
            dataKey="share_pct"
            name="Non-zero share"
            fill="var(--series-1)"
            radius={[4, 4, 0, 0]}
            maxBarSize={28}
            isAnimationActive={false}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function SmartTable({ series }: { series: SmartTrendPoint[] }) {
  return (
    <table className="data">
      <thead>
        <tr>
          <th scope="col">Period</th>
          <th scope="col" className="num">
            p50
          </th>
          <th scope="col" className="num">
            p95
          </th>
          <th scope="col" className="num">
            Non-zero share
          </th>
          <th scope="col" className="num">
            Sampled drives
          </th>
        </tr>
      </thead>
      <tbody>
        {series.map((p) => (
          <tr key={p.period}>
            <td>{p.period}</td>
            <td className="num">{formatSmart(p.p50)}</td>
            <td className="num">{formatSmart(p.p95)}</td>
            <td className="num">
              {p.nonzero_share === null ? '–' : formatPct(p.nonzero_share * 100, 1)}
            </td>
            <td className="num">{formatInt(p.n_drives)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
