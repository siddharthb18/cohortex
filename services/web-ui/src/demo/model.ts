/**
 * Static demo data model and derivations (synthetic numbers only). Pure functions with no
 * imports besides ./stats, so scripts/generate-demo-data.ts can share them with the app and the
 * recorded investigation's evidence stays consistent with the Fleet and Cohort pages.
 */
import { afrCi } from './stats.ts';

export type DemoSource = 'backblaze' | 'alibaba';

export interface DemoMonth {
  /** YYYY-MM */
  period: string;
  drive_days: number;
  failures: number;
  /** Drives observed on the month's last day. */
  drives: number;
}

export interface DemoModel {
  model: string;
  media: 'hdd' | 'ssd';
  capacity_bytes: number | null;
  months: DemoMonth[];
  /** SMART counters drift upwards from this month on (the demo's degrading cohort). */
  smart_drift?: { from: string; attrs: number[]; strength: number };
  /** Age in days on the first month, used for age at failure. */
  base_age_days: number;
}

export interface DemoFleetData {
  note: string;
  generated_at: string;
  sources: Record<DemoSource, DemoModel[]>;
}

// ---------------------------------------------------------------------------
// Deterministic randomness
// ---------------------------------------------------------------------------

export function hashString(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i += 1) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

export function rng(seed: string): () => number {
  let a = hashString(seed);
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ---------------------------------------------------------------------------
// Windows and grouping
// ---------------------------------------------------------------------------

export function monthsInWindow(model: DemoModel, from: string, to: string): DemoMonth[] {
  const first = from.slice(0, 7);
  const last = to.slice(0, 7);
  return model.months.filter((m) => m.period >= first && m.period <= last);
}

export function monthToQuarter(period: string): string {
  const year = period.slice(0, 4);
  const month = Number(period.slice(5, 7));
  return `${year}Q${Math.floor((month - 1) / 3) + 1}`;
}

function groupBy<T>(items: T[], key: (item: T) => string): Map<string, T[]> {
  const out = new Map<string, T[]>();
  for (const item of items) {
    const k = key(item);
    const list = out.get(k);
    if (list) list.push(item);
    else out.set(k, [item]);
  }
  return out;
}

const round = (x: number, digits: number) => Number(x.toFixed(digits));

// ---------------------------------------------------------------------------
// fleet-api equivalents
// ---------------------------------------------------------------------------

export function afrSeries(
  model: DemoModel,
  from: string,
  to: string,
  granularity: 'quarter' | 'month',
) {
  const months = monthsInWindow(model, from, to);
  const groups = groupBy(months, (m) =>
    granularity === 'quarter' ? monthToQuarter(m.period) : m.period,
  );
  return [...groups.entries()].map(([period, ms]) => {
    const drive_days = ms.reduce((s, m) => s + m.drive_days, 0);
    const failures = ms.reduce((s, m) => s + m.failures, 0);
    return { period, drive_days, failures, ...afrCi(failures, drive_days) };
  });
}

function totals(models: DemoModel[], from: string, to: string) {
  let driveDays = 0;
  let failures = 0;
  let drives = 0;
  for (const model of models) {
    const ms = monthsInWindow(model, from, to);
    driveDays += ms.reduce((s, m) => s + m.drive_days, 0);
    failures += ms.reduce((s, m) => s + m.failures, 0);
    drives += ms.reduce((max, m) => Math.max(max, m.drives), 0);
  }
  return { driveDays, failures, drives };
}

export function fleetSummary(data: DemoFleetData, source: DemoSource, from: string, to: string) {
  const t = totals(data.sources[source], from, to);
  return {
    source,
    from,
    to,
    drives: t.drives,
    drive_days: t.driveDays,
    failures: t.failures,
    ...(t.driveDays > 0
      ? afrCi(t.failures, t.driveDays)
      : { afr_pct: 0, ci_low_pct: 0, ci_high_pct: 0 }),
    method: 'exact_poisson_95' as const,
    generated_at: data.generated_at,
  };
}

export function compareCohorts(
  data: DemoFleetData,
  source: DemoSource,
  from: string,
  to: string,
  minDrives = 60,
  limit = 20,
) {
  const fleet = totals(data.sources[source], from, to);
  const fleetAfr = fleet.driveDays > 0 ? (fleet.failures * 36500) / fleet.driveDays : 0;
  const rows = data.sources[source]
    .map((model) => {
      const ms = monthsInWindow(model, from, to);
      const last = ms[ms.length - 1];
      if (!last || last.drives < minDrives) return null;
      const drive_days = ms.reduce((s, m) => s + m.drive_days, 0);
      const failures = ms.reduce((s, m) => s + m.failures, 0);
      const ci = afrCi(failures, drive_days);
      return {
        model: model.model,
        drive_days,
        failures,
        ...ci,
        rate_ratio_vs_fleet: fleetAfr > 0 ? ci.afr_pct / fleetAfr : 0,
      };
    })
    .filter((r): r is NonNullable<typeof r> => r !== null)
    .sort((a, b) => b.afr_pct - a.afr_pct || a.model.localeCompare(b.model));
  return rows.slice(0, limit);
}

// ---------------------------------------------------------------------------
// Synthetic SMART trends and failed drives
// ---------------------------------------------------------------------------

interface AttrProfile {
  kind: 'counter' | 'gauge' | 'growing';
  p50: number;
  p95: number;
  share: number;
}

function profile(attr: number, media: 'hdd' | 'ssd'): AttrProfile {
  switch (attr) {
    case 9:
      return {
        kind: 'growing',
        p50: media === 'hdd' ? 36000 : 14000,
        p95: media === 'hdd' ? 47000 : 19000,
        share: 1,
      };
    case 12:
      return { kind: 'gauge', p50: 18, p95: 41, share: 1 };
    case 194:
      return {
        kind: 'gauge',
        p50: media === 'hdd' ? 31 : 38,
        p95: media === 'hdd' ? 39 : 47,
        share: 1,
      };
    case 193:
      return { kind: 'growing', p50: 9200, p95: 31000, share: 1 };
    case 240:
      return { kind: 'growing', p50: 33000, p95: 44000, share: 1 };
    case 241:
    case 242:
      return { kind: 'growing', p50: 5.1e10, p95: 9.8e10, share: 1 };
    case 173:
      return { kind: 'growing', p50: 140, p95: 610, share: 0.97 };
    case 174:
      return { kind: 'gauge', p50: 3, p95: 14, share: 0.71 };
    case 195:
      return { kind: 'counter', p50: 0, p95: 160, share: 0.09 };
    default:
      return { kind: 'counter', p50: 0, p95: 4, share: 0.018 };
  }
}

export function smartTrend(
  model: DemoModel,
  attr: number,
  from: string,
  to: string,
  granularity: 'quarter' | 'month',
) {
  const prof = profile(attr, model.media);
  const drift = model.smart_drift;
  const seedBase = hashString(model.model) % 1000;
  const monthly = monthsInWindow(model, from, to).map((m) => {
    const r = rng(`${model.model}|${attr}|${m.period}`);
    const index = model.months.indexOf(m);
    const drifting = drift && drift.attrs.includes(attr) && m.period >= drift.from;
    const boost = drifting ? 1 + drift.strength * (1 + (m.period > drift.from ? 0.6 : 0)) : 1;
    const jitter = 0.9 + r() * 0.2;
    const growth = prof.kind === 'growing' ? 1 + index * 0.018 : 1;
    const skew = 0.85 + (seedBase / 1000) * 0.3;
    let p50 = prof.p50 * growth * jitter * skew;
    let p95 = prof.p95 * growth * (0.92 + r() * 0.16) * skew * (drifting ? boost : 1);
    let share = Math.min(1, prof.share * (0.85 + r() * 0.3) * skew * (drifting ? boost : 1));
    if (prof.kind === 'counter') {
      p50 = drifting && boost > 3 ? 1 : 0;
      p95 = Math.round(p95);
      share = round(share, 4);
    } else {
      p50 = round(p50, p50 > 100 ? 0 : 1);
      p95 = round(p95, p95 > 100 ? 0 : 1);
      share = round(share, 4);
    }
    return {
      period: m.period,
      p50,
      p95,
      nonzero_share: share,
      n_drives: Math.max(1, Math.round(m.drives / 100) + m.failures),
    };
  });
  if (granularity === 'month') return monthly;
  const groups = groupBy(monthly, (p) => monthToQuarter(p.period));
  return [...groups.entries()].map(([period, ps]) => {
    const mean = (f: (p: (typeof ps)[number]) => number) =>
      ps.reduce((s, p) => s + f(p), 0) / ps.length;
    const p50 = mean((p) => p.p50);
    const p95 = mean((p) => p.p95);
    return {
      period,
      p50: round(p50, p50 > 100 ? 0 : 1),
      p95: round(p95, p95 > 100 ? 0 : 1),
      nonzero_share: round(
        mean((p) => p.nonzero_share),
        4,
      ),
      n_drives: ps.reduce((max, p) => Math.max(max, p.n_drives), 0),
    };
  });
}

const SERIAL_PREFIX: Record<string, string> = { ST: 'ZL', HG: '8H', TO: 'X0', WD: '2B' };

function daysInMonth(period: string): number {
  const [y, m] = period.split('-').map(Number);
  return new Date(Date.UTC(y ?? 2000, m ?? 1, 0)).getUTCDate();
}

export function failedDrives(model: DemoModel, source: DemoSource, from: string, to: string) {
  const kept = model.media === 'hdd' ? [5, 187, 197, 198] : [5, 171, 172, 187];
  const drift = model.smart_drift;
  const items = monthsInWindow(model, from, to).flatMap((m) =>
    Array.from({ length: m.failures }, (_, i) => {
      const r = rng(`${model.model}|fail|${m.period}|${i}`);
      const day = 1 + Math.floor(r() * daysInMonth(m.period));
      const failed_on = `${m.period}-${String(day).padStart(2, '0')}`;
      const monthIndex = model.months.indexOf(m);
      const age_days = model.base_age_days + monthIndex * 30 + day - Math.floor(r() * 400);
      const drifting = drift !== undefined && m.period >= drift.from;
      const last_smart: Record<string, number> = {};
      for (const attr of kept) {
        const signal = r() < (drifting && drift.attrs.includes(attr) ? 0.62 : 0.28);
        last_smart[String(attr)] = signal ? Math.round(1 + r() * r() * (drifting ? 480 : 120)) : 0;
      }
      const prefix = SERIAL_PREFIX[model.model.slice(0, 2)] ?? 'SN';
      const serial = `${prefix}${hashString(`${model.model}|${m.period}|${i}`).toString(36).toUpperCase().padStart(7, '0')}`;
      const drive_id =
        source === 'alibaba' ? `${model.model}:${10000 + (hashString(serial) % 90000)}` : serial;
      return { drive_id, failed_on, age_days: Math.max(30, age_days), last_smart };
    }),
  );
  return items.sort(
    (a, b) => b.failed_on.localeCompare(a.failed_on) || a.drive_id.localeCompare(b.drive_id),
  );
}
