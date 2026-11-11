import { describe, expect, it } from 'vitest';
import type { Alert } from '@/lib/api';
import { vulnerabilitiesCsvText } from './vulnerabilitiesCsv';

const alert = (over: Partial<Alert>): Alert => ({ id: 'a1', severity: 'high', title: 'Windows 10 is out of support', clientName: 'Acme', createdAt: '2026-11-10T09:00:00Z', ...over }) as Alert;

describe('vulnerabilitiesCsvText', () => {
  it('writes a header and one row per finding, with the tool worded by the page', () => {
    const lines = vulnerabilitiesCsvText([alert({ description: '12 devices, in Acme' }), alert({ id: 'a2', severity: 'critical', clientName: undefined, description: undefined })], () => 'NinjaOne')
      .replace('﻿', '')
      .split('\r\n');
    expect(lines[0]).toBe('Severity,Client,Finding,Details,Tool,First seen,Alert');
    expect(lines[1]).toBe('high,Acme,Windows 10 is out of support,"12 devices, in Acme",NinjaOne,2026-11-10T09:00:00Z,/alerts/a1');
    expect(lines[2]).toBe('critical,,Windows 10 is out of support,,NinjaOne,2026-11-10T09:00:00Z,/alerts/a2');
  });

  it('makes a title that looks like a formula safe for a spreadsheet, and an empty list is just the header', () => {
    expect(vulnerabilitiesCsvText([alert({ title: '=HYPERLINK("http://evil")' })], () => 'x')).toContain(`"'=HYPERLINK(""http://evil"")"`);
    expect(vulnerabilitiesCsvText([], () => 'x').replace('﻿', '')).toBe('Severity,Client,Finding,Details,Tool,First seen,Alert\r\n');
  });
});
