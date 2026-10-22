import type { Source } from './api/types';
import type { QuarterLabel } from './lib/quarters';

/** Static demo mode: built with VITE_DEMO=1, reads canned files from public/demo/. */
export const IS_DEMO = import.meta.env.VITE_DEMO === '1' || import.meta.env.VITE_DEMO === 'true';

/** Same-origin API prefixes, proxied by Vite in development and by nginx in production. */
export const AGENT_API = '/api/agent';
export const FLEET_API = '/api/fleet';

export interface SourceInfo {
  id: Source;
  label: string;
  media: string;
  /** Quarters the serving tables hold by default (design §3: last six Backblaze quarters, Alibaba 2018-2019). */
  first: QuarterLabel;
  last: QuarterLabel;
  /** Default Fleet window. */
  defaultFrom: QuarterLabel;
  defaultTo: QuarterLabel;
  smartAttrs: readonly number[];
}

// SMART attributes kept in serving tables (contracts §1).
export const SOURCES: Record<Source, SourceInfo> = {
  backblaze: {
    id: 'backblaze',
    label: 'Backblaze',
    media: 'HDD',
    first: '2025Q1',
    last: '2026Q2',
    defaultFrom: '2026Q2',
    defaultTo: '2026Q2',
    smartAttrs: [5, 9, 12, 187, 188, 193, 194, 197, 198, 199, 240, 241, 242],
  },
  alibaba: {
    id: 'alibaba',
    label: 'Alibaba',
    media: 'SSD',
    first: '2018Q1',
    last: '2019Q4',
    defaultFrom: '2019Q1',
    defaultTo: '2019Q4',
    smartAttrs: [5, 9, 12, 171, 172, 173, 174, 175, 187, 188, 194, 195, 199],
  },
};

export const SMART_ATTR_NAMES: Record<number, string> = {
  5: 'Reallocated sectors',
  9: 'Power-on hours',
  12: 'Power cycle count',
  171: 'Program fail count',
  172: 'Erase fail count',
  173: 'Wear leveling count',
  174: 'Unexpected power loss count',
  187: 'Reported uncorrectable errors',
  188: 'Command timeout',
  193: 'Load cycle count',
  194: 'Temperature',
  195: 'Hardware ECC recovered',
  197: 'Current pending sectors',
  198: 'Offline uncorrectable',
  199: 'UDMA CRC error count',
  240: 'Head flying hours',
  241: 'Total LBAs written',
  242: 'Total LBAs read',
};

export function smartAttrLabel(attr: number): string {
  const name = SMART_ATTR_NAMES[attr];
  return name ? `SMART ${attr}: ${name}` : `SMART ${attr}`;
}

/** contracts §5/§4: compare default min_drives. */
export const DEFAULT_MIN_DRIVES = 60;
