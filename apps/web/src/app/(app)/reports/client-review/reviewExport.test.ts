import { beforeEach, describe, expect, it } from 'vitest';

import type { Review } from './ClientReview';
import { answeredAutomatically, csvCell, csvFileName, loadFolded, openCounts, openLabel, reviewCsv, saveFolded } from './reviewExport';

const base = (): Review => ({
  client_id: 'c1',
  client_name: 'Airport Security Park, LLC',
  generated_at: '2026-10-28T12:00:00Z',
  window_days: 30,
  devices: { endpoints: 0, coverage: [], stale_agents: 0, offline: 0, with_known_exploited: null, with_ransomware_exploit: null },
  mfa: null,
  secure_score: null,
  alerts: { open: 0, critical_open: 0, high_open: 0, opened_30d: 0, closed_30d: 0 },
  cases: { open: 0, opened_30d: 0, resolved_30d: 0 },
  readiness: {
    met: 1,
    partly: 0,
    not_met: 0,
    unknown: 1,
    items: [
      { key: 'edr', question: 'EDR on every computer?', status: 'met', evidence: '20 of 20 report Huntress' },
      { key: 'backups', question: 'Backups tested?', status: 'unknown', evidence: 'Not collected', note: 'ask them, then "tell us"' },
    ],
  },
  tech_stack: [
    { key: 'edr', group: 'Security', question: 'EDR', status: 'seen', suggested: 'Huntress', evidence: 'seen' },
    { key: 'siem', group: 'Security', question: 'SIEM', status: 'unknown', suggested: null, evidence: '' },
  ],
  m365: [
    { group: 'Entra', question: 'Block legacy authentication', status: 'needs_person', evidence: '', license: 'Needs Microsoft Entra ID P1.' },
    { group: 'Entra', question: 'MFA for admins', status: 'met', evidence: 'Every administrator has Multi-Factor.', manual: true, note: '=HYPERLINK("http://x")' },
  ],
  assess: [
    { sheet: 'Network', group: 'Firewall', question: 'Firewall patched?', status: 'needs_person', evidence: '' },
    { sheet: 'Network', group: 'Firewall', question: 'Not relevant here', status: 'not_applicable', evidence: '', manual: true },
  ],
});

describe('answeredAutomatically', () => {
  it('is true for an answer A.C.O.R.N worked out, and false for open questions, typed answers and a person choosing not applicable', () => {
    expect(answeredAutomatically('met', false)).toBe(true);
    expect(answeredAutomatically('not_met', undefined)).toBe(true);
    expect(answeredAutomatically('seen', undefined)).toBe(true);
    expect(answeredAutomatically('met', true)).toBe(false);
    expect(answeredAutomatically('unknown', false)).toBe(false);
    expect(answeredAutomatically('needs_person', false)).toBe(false);
    expect(answeredAutomatically('not_applicable', false)).toBe(false);
  });
});

describe('open counts', () => {
  it('counts the questions nobody has answered in each section', () => {
    expect(openCounts(base())).toEqual({ readiness: 1, tech: 1, m365: 1, assess: 1 });
  });
  it('treats a missing section as having none open', () => {
    const r = base();
    delete r.tech_stack;
    delete r.m365;
    delete r.assess;
    expect(openCounts(r)).toEqual({ readiness: 1, tech: 0, m365: 0, assess: 0 });
  });
  it('words the heading label, and says nothing for a section with no questions', () => {
    expect(openLabel(3, 10)).toBe('3 of 10 open');
    expect(openLabel(0, 10)).toBe('all answered');
    expect(openLabel(0, 0)).toBe('');
  });
});

describe('csvCell', () => {
  it('quotes commas, quotes and line breaks, and defuses a cell a spreadsheet would run as a formula', () => {
    expect(csvCell('plain')).toBe('plain');
    expect(csvCell('a,b')).toBe('"a,b"');
    expect(csvCell('say "hi"')).toBe('"say ""hi"""');
    expect(csvCell('two\nlines')).toBe('"two\nlines"');
    expect(csvCell('=HYPERLINK("http://x")')).toBe('"\'=HYPERLINK(""http://x"")"');
    expect(csvCell('+1')).toBe("'+1");
    expect(csvCell('-2')).toBe("'-2");
    expect(csvCell('@SUM(A1)')).toBe("'@SUM(A1)");
    expect(csvCell(null)).toBe('');
    expect(csvCell(7)).toBe('7');
  });
});

describe('reviewCsv', () => {
  it('has a header and a row per question in every section, saying who answered and the licence', () => {
    const rows = reviewCsv(base()).trimEnd().split('\r\n');
    expect(rows[0]).toBe('Section,Group,Question,Status,Answered by,Evidence,Note,Licence');
    expect(rows).toHaveLength(1 + 2 + 2 + 2 + 2);
    expect(rows[1]).toBe('Cyber-insurance readiness,,EDR on every computer?,met,automatic,20 of 20 report Huntress,,');
    expect(rows[2]).toContain('not answered');
    expect(rows[2]).toContain('"ask them, then ""tell us"""');
    expect(rows[3]).toBe('Technology stack,Security,EDR,Huntress,automatic,seen,,');
    expect(rows[4]).toContain('ask the client');
    expect(rows[5]).toBe('Microsoft 365,Entra,Block legacy authentication,needs_person,not answered,,,Needs Microsoft Entra ID P1.');
    expect(rows[6]).toContain('typed by a person');
    // a typed note that looks like a formula is defused
    expect(rows[6]).toContain("'=HYPERLINK");
    expect(rows[8]).toContain('typed by a person');
  });
  it('names the file after the client and the day', () => {
    expect(csvFileName(base())).toBe('client-review-airport-security-park-llc-2026-10-28.csv');
    expect(csvFileName({ ...base(), client_name: null })).toBe('client-review-client-2026-10-28.csv');
  });
});

describe('folded sections', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });
  it('are remembered and read back, and rubbish in storage means nothing is folded', () => {
    expect(loadFolded()).toEqual([]);
    saveFolded(['m365', 'assess']);
    expect(loadFolded()).toEqual(['m365', 'assess']);
    window.localStorage.setItem('client-review-folded', '{"not":"a list"}');
    expect(loadFolded()).toEqual([]);
    window.localStorage.setItem('client-review-folded', '["a",1,null,"b"]');
    expect(loadFolded()).toEqual(['a', 'b']);
    window.localStorage.setItem('client-review-folded', 'not json');
    expect(loadFolded()).toEqual([]);
  });
});
