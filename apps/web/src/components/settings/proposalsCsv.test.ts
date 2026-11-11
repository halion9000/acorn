import { describe, expect, it } from 'vitest';
import type { AgentProposal } from '@/lib/api';
import { proposalsCsvText } from './proposalsCsv';

const base: AgentProposal = {
  id: 'p1',
  agent: 'cipher',
  action_type: 'close_alert',
  target: 'alert 42',
  summary: 'Closed as a duplicate, the same device',
  rung: 'act_tell',
  evidence: [{ label: 'Same device in alert 41' }, { label: 'Ticket 123', url: 'https://x.test' }],
  confidence: 0.876,
  approval_id: null,
  outcome: 'accepted',
  outcome_note: null,
  outcome_at: null,
  created_at: '2026-11-10T09:00:00Z',
};

describe('proposalsCsvText', () => {
  it('writes a header and one row per proposal, in plain words, with evidence names joined', () => {
    const lines = proposalsCsvText([base, { ...base, id: 'p2', rung: 'shadow', confidence: null, outcome: 'rejected', outcome_note: 'wrong device', evidence: [] }])
      .replace('\uFEFF', '')
      .split('\r\n');
    expect(lines[0]).toBe('When,Agent,Action,Target,Summary,How far it went,Confidence,Outcome,Outcome note,Evidence');
    expect(lines[1]).toBe('2026-11-10T09:00:00Z,cipher,close_alert,alert 42,"Closed as a duplicate, the same device",Did it and told us,88%,Agreed,,Same device in alert 41; Ticket 123');
    expect(lines[2]).toBe('2026-11-10T09:00:00Z,cipher,close_alert,alert 42,"Closed as a duplicate, the same device",Would have done (shadow),,Rejected,wrong device,');
  });

  it('makes a summary that looks like a formula safe for a spreadsheet', () => {
    const text = proposalsCsvText([{ ...base, summary: '=HYPERLINK("http://evil")' }]);
    expect(text).toContain("\"'=HYPERLINK(\"\"http://evil\"\")\"");
  });
});
