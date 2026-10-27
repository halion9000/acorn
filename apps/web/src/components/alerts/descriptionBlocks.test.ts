import { describe, expect, it } from 'vitest';
import { descriptionBlocks } from './descriptionBlocks';

const NINJA =
  "Custom Fields condition was matched: 'RDP 3389 Check' Device: SERVER-WEB-SQL Organization: Texas Society of CPA'S Source: CONDITION_CUSTOM_FIELD Device type: WINDOWS_SERVER Device is online Last contact: 2026-10-26T21:38:06.766Z Severity: CRITICAL Priority: HIGH Raised: 2026-10-26T21:57:10.366Z Last updated: 2026-10-26T21:57:10.366Z Condition data: {\"message\":{\"code\":\"agent_customfields_matched\",\"params\":{\"conditionName\":\"RDP 3389 Check\"}}}";

describe('descriptionBlocks', () => {
  it('splits a NinjaOne run-on line into fields, with the JSON formatted as code', () => {
    const blocks = descriptionBlocks(NINJA);
    expect(blocks[0]).toEqual({ kind: 'text', text: "Custom Fields condition was matched: 'RDP 3389 Check'" });
    const fields = blocks.find((b) => b.kind === 'fields');
    expect(fields && fields.kind === 'fields' ? fields.rows : []).toEqual([
      ['Device', 'SERVER-WEB-SQL'],
      ['Organization', "Texas Society of CPA'S"],
      ['Source', 'CONDITION_CUSTOM_FIELD'],
      ['Device type', 'WINDOWS_SERVER'],
      ['Status', 'online'],
      ['Last contact', '2026-10-26T21:38:06.766Z'],
      ['Severity', 'CRITICAL'],
      ['Priority', 'HIGH'],
      ['Raised', '2026-10-26T21:57:10.366Z'],
      ['Last updated', '2026-10-26T21:57:10.366Z'],
    ]);
    const code = blocks.find((b) => b.kind === 'code');
    expect(code && code.kind === 'code' ? code.text : '').toContain('"conditionName": "RDP 3389 Check"');
    expect(blocks.some((b) => b.kind === 'text' && b.text === 'Condition data')).toBe(true);
  });

  it('keeps prose paragraphs and turns line-per-field text (Huntress, ThreatMate) into a table', () => {
    const huntress = 'Unexpected Country - Colombia\n\nHuntress managed ITDR escalation: Microsoft 365 Login (CO). Status: open.\nPerson: sbrownfield@xstrememd.com\nSign-in addresses: 138.84.41.144\nLogins seen: 1\nHuntress asks: Response Needed';
    const blocks = descriptionBlocks(huntress);
    expect(blocks[0]).toEqual({ kind: 'text', text: 'Unexpected Country - Colombia' });
    expect(blocks[1].kind).toBe('text');
    const fields = blocks[2];
    expect(fields.kind === 'fields' ? fields.rows.map((r) => r[0]) : []).toEqual(['Person', 'Sign-in addresses', 'Logins seen', 'Huntress asks']);
  });

  it('does not turn a sentence with a colon into a field, and a lone field stays text', () => {
    expect(descriptionBlocks('Custom Fields condition was matched: it fired')).toEqual([{ kind: 'text', text: 'Custom Fields condition was matched: it fired' }]);
    expect(descriptionBlocks('Asset: www.example.com')).toEqual([{ kind: 'text', text: 'Asset: www.example.com' }]);
  });

  it('leaves JSON that does not parse as text, and splits a run-on only when three known labels appear', () => {
    expect(descriptionBlocks('Note: {not json}\nOther: x').some((b) => b.kind === 'code')).toBe(false);
    expect(descriptionBlocks('Device: PC-1 Severity: high')).toEqual([{ kind: 'text', text: 'Device: PC-1 Severity: high' }]);
  });

  it('is empty for nothing', () => {
    expect(descriptionBlocks('')).toEqual([]);
    expect(descriptionBlocks(null)).toEqual([]);
    expect(descriptionBlocks('   \n ')).toEqual([]);
  });
});
