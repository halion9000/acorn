import { describe, expect, it } from 'vitest';
import { buildSummary, type SummaryInput } from './summaryText';

const base = (o: Partial<SummaryInput> = {}): SummaryInput => ({
  name: 'Acme Dental',
  days: 7,
  now: new Date('2026-10-26T12:00:00Z'),
  checks: [],
  changes: [],
  history: null,
  compare: null,
  counts: null,
  label: (s, k) => `${s}: ${k.replace(/_/g, ' ')}`,
  ...o,
});

describe('buildSummary', () => {
  it('heads the draft with the client, the kind of update and the dates', () => {
    expect(buildSummary(base()).split('\n')[0]).toBe('Acme Dental: weekly update, 2026-10-19 to 2026-10-26');
    expect(buildSummary(base({ days: 90 })).split('\n')[0]).toBe('Acme Dental: quarterly review, 2026-07-28 to 2026-10-26');
  });

  it('says how the score moved, in words, and how the client compares', () => {
    const up = buildSummary(base({ history: { first: 70, last: 78, change: 8, days_with_data: 7 }, compare: { score: 78, fleet_average: 72, similar_average: 65, similar_clients: 14 } }));
    expect(up).toContain('Score: 78%, up 8 points from 70% over the 7 days of history we have.');
    expect(up).toContain('the average across clients is 72%, and 65% for 14 clients of about the same size');
    expect(buildSummary(base({ history: { first: 70, last: 69, change: -1, days_with_data: 5 } }))).toContain('down 1 point from 70%');
    expect(buildSummary(base({ history: { first: 70, last: 70, change: 0, days_with_data: 5 } }))).toContain('70%, unchanged from 70%');
  });

  it('does not invent a trend when the history is short or missing, and says when there is no score at all', () => {
    expect(buildSummary(base({ history: { first: 80, last: 80, change: 0, days_with_data: 1 } }))).toContain('only started keeping the score recently');
    expect(buildSummary(base({ compare: { score: 61, fleet_average: null, similar_average: null, similar_clients: 0 } }))).toContain('Score today: 61%.');
    expect(buildSummary(base())).toContain('No score yet');
  });

  it('lists what needs attention worst first, caps the list, and leaves accepted risks out of it', () => {
    const checks = [
      { source: 'ninjaone', key: 'patching', status: 'partly', accepted: false },
      { source: 'slide', key: 'backup', status: 'not_met', accepted: false },
      { source: 'huntress', key: 'agents', status: 'not_met', accepted: true },
      ...['a', 'b', 'c', 'd', 'e'].map((k) => ({ source: 'x', key: k, status: 'partly', accepted: false })),
    ];
    const text = buildSummary(base({ checks }));
    expect(text).toContain('7 checks need attention now: slide: backup; ninjaone: patching;');
    expect(text).toContain('and 2 more.');
    expect(text).not.toContain('huntress: agents');
    expect(text).toContain('1 more is an accepted risk');
    expect(buildSummary(base({ checks: [{ source: 'a', key: 'k', status: 'met', accepted: false }] }))).toContain('Nothing needs attention right now.');
  });

  it('separates what got worse from what got better and ignores a check seen for the first time', () => {
    const changes = [
      { source: 'slide', key: 'backup', status: 'not_met', previous_status: 'met' },
      { source: 'ninjaone', key: 'patching', status: 'met', previous_status: 'partly' },
      { source: 'cipp', key: 'new_check', status: 'not_met', previous_status: null },
    ];
    const text = buildSummary(base({ changes }));
    expect(text).toContain('Got worse in this period: slide: backup.');
    expect(text).toContain('Got better in this period: ninjaone: patching.');
    expect(text).not.toContain('new check');
    expect(buildSummary(base({ changes: [] }))).toContain('No check changed in this period.');
  });

  it('adds devices, Multi-Factor and moved counts for a quarter only, and never what is billed or any price', () => {
    const extra: Partial<SummaryInput> = {
      devices: { devices: 52, needs_attention: 4 },
      identity: { people: 30, with_mfa: 27, admins_without_mfa: 1 },
      counts: [
        { source: 'ninjaone', item: 'Windows workstations', count: 52, change: 6 },
        { source: 'huntress', item: 'Agents', count: 50, change: 0 },
        { source: 'cipp', item: 'Business Basic', count: 30, change: null },
        { source: 'halopsa', item: 'NinjaOne RMM (Included)', count: 50, change: 4 },
      ],
    };
    const quarter = buildSummary(base({ days: 90, ...extra }));
    expect(quarter).toContain('Devices: 52, of which 4 need attention.');
    expect(quarter).toContain('Multi-Factor: 27 of 30 people covered; 1 administrator without it.');
    expect(quarter).toContain('Windows workstations (ninjaone) 46 to 52');
    expect(quarter).not.toContain('Agents (huntress)');
    expect(quarter).not.toContain('NinjaOne RMM');
    const week = buildSummary(base({ days: 7, ...extra }));
    expect(week).not.toContain('Devices:');
    expect(week).not.toContain('Multi-Factor:');
  });

  it('ends by saying it is a draft and was sent to no one', () => {
    expect(buildSummary(base()).trimEnd().endsWith('nothing here has been sent to anyone.')).toBe(true);
  });
});
