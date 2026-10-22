import { describe, expect, it } from 'vitest';
import {
  initialStreamState,
  parseSseData,
  streamReducer,
  summarizeSteps,
} from './investigationStream';
import type { Report, Step } from '../api/types';

const plan: Step = {
  seq: 1,
  node: 'agent',
  kind: 'plan',
  payload: {
    plan: {
      restated_question: 'Q',
      scope: { source: 'backblaze', models: [], date_from: null, date_to: null },
      tasks: [{ id: 't1', kind: 'data', goal: 'g', depends_on: [] }],
    },
  },
  started_at: '2026-10-21T10:00:00Z',
  ended_at: '2026-10-21T10:00:01Z',
};
const tool = (seq: number, ok = true): Step => ({
  seq,
  node: 'agent',
  kind: 'tool_call',
  payload: { tool: 'fleet.cohort_afr', args: {}, evidence_id: `ev_${seq}`, ok, summary: 's' },
  started_at: '2026-10-21T10:00:02Z',
  ended_at: null,
});
const check: Step = {
  seq: 9,
  node: 'checker',
  kind: 'check',
  payload: { supported: 5, unsupported: 1, notes: ['n'] },
  started_at: '2026-10-21T10:00:05Z',
  ended_at: '2026-10-21T10:00:05Z',
};

const report = { question: 'Q' } as unknown as Report;

describe('streamReducer', () => {
  it('moves from connecting to streaming on the first step', () => {
    let s = streamReducer(initialStreamState, { type: 'connect' });
    expect(s.phase).toBe('connecting');
    s = streamReducer(s, { type: 'step', step: plan });
    expect(s.phase).toBe('streaming');
    expect(s.steps).toHaveLength(1);
  });

  it('keeps steps ordered by seq and de-duplicates replays', () => {
    let s = streamReducer(initialStreamState, { type: 'connect' });
    s = streamReducer(s, { type: 'step', step: tool(3) });
    s = streamReducer(s, { type: 'step', step: plan });
    s = streamReducer(s, { type: 'step', step: tool(2) });
    // A reconnect replays stored steps first (implementation-notes §7).
    s = streamReducer(s, { type: 'step', step: plan });
    s = streamReducer(s, { type: 'step', step: { ...tool(3), ended_at: '2026-10-21T10:00:03Z' } });
    expect(s.steps.map((x) => x.seq)).toEqual([1, 2, 3]);
    expect(s.steps[2]?.ended_at).toBe('2026-10-21T10:00:03Z');
  });

  it('stores the report and status on the terminal report event', () => {
    let s = streamReducer(initialStreamState, { type: 'connect' });
    s = streamReducer(s, {
      type: 'report',
      data: { status: 'completed', report, markdown: '# R' },
    });
    expect(s.phase).toBe('done');
    expect(s.status).toBe('completed');
    expect(s.report).toBe(report);
    expect(s.markdown).toBe('# R');
  });

  it('records a terminal error event', () => {
    const s = streamReducer(initialStreamState, {
      type: 'error',
      data: { status: 'budget_exceeded', message: 'Tool-call budget of 20 reached' },
    });
    expect(s.phase).toBe('failed');
    expect(s.status).toBe('budget_exceeded');
    expect(s.error).toMatch(/budget/);
  });

  it('ignores a connection drop after a terminal event', () => {
    let s = streamReducer(initialStreamState, {
      type: 'report',
      data: { status: 'completed', report, markdown: null },
    });
    s = streamReducer(s, { type: 'connection_lost', message: 'closed' });
    expect(s.phase).toBe('done');
    expect(s.error).toBeNull();
  });

  it('marks a live stream as failed when the connection is lost', () => {
    let s = streamReducer(initialStreamState, { type: 'connect' });
    s = streamReducer(s, { type: 'connection_lost', message: 'Lost connection' });
    expect(s.phase).toBe('failed');
    expect(s.error).toBe('Lost connection');
  });

  it('resets', () => {
    const s = streamReducer({ ...initialStreamState, steps: [plan] }, { type: 'reset' });
    expect(s).toEqual(initialStreamState);
  });
});

describe('summarizeSteps', () => {
  it('counts tool calls, failed calls and the latest check', () => {
    const summary = summarizeSteps([plan, tool(2), tool(3, false), check]);
    expect(summary).toEqual({ toolCalls: 2, toolErrors: 1, supported: 5, unsupported: 1 });
  });
  it('returns null check counts before the checker runs', () => {
    expect(summarizeSteps([plan])).toEqual({
      toolCalls: 0,
      toolErrors: 0,
      supported: null,
      unsupported: null,
    });
  });
});

describe('parseSseData', () => {
  it('parses JSON data', () => {
    expect(parseSseData<{ a: number }>('{"a":1}')).toEqual({ a: 1 });
  });
  it('returns null on malformed data', () => {
    expect(parseSseData('{oops')).toBeNull();
  });
});
