import { describe, expect, it } from 'vitest';
import type { Alert, Case } from '@/lib/api';
import { alertsCsvText } from './AlertsView';
import { casesCsvText } from '../cases/CasesView';

describe('alertsCsvText', () => {
  it('has a header and one row per alert with its users joined, and defuses a title that starts like a formula', () => {
    const a = { id: '1', title: '=HYPERLINK("http://evil")', severity: 'high', status: 'new', source: 'huntress', clientName: 'Acme', device: 'PC-1', affectedUsers: ['a@x.com', 'b@x.com'], assignee: undefined, createdAt: '2026-11-08T10:00:00Z' } as unknown as Alert;
    const lines = alertsCsvText([a]).replace('﻿', '').split('\r\n');
    expect(lines[0]).toBe('Title,Severity,Status,Source,Client,Device,Users,Assignee,Created');
    expect(lines[1]).toBe('"\'=HYPERLINK(""http://evil"")",high,new,huntress,Acme,PC-1,a@x.com; b@x.com,,2026-11-08T10:00:00Z');
  });
  it('is only the header with no alerts', () => {
    expect(alertsCsvText([]).replace('﻿', '')).toBe('Title,Severity,Status,Source,Client,Device,Users,Assignee,Created\r\n');
  });
});

describe('casesCsvText', () => {
  it('has a header and a row per case with the alert count taken from the list when it has no count', () => {
    const c = { id: '1', caseNumber: 'INC-7', title: 'Takeover, Acme', status: 'open', severity: 'critical', clientName: 'Acme', assignee: 'Hal', alertIds: ['a', 'b'], tags: ['bec', 'm365'], createdAt: '2026-11-08T10:00:00Z' } as unknown as Case;
    const lines = casesCsvText([c]).replace('﻿', '').split('\r\n');
    expect(lines[0]).toBe('Case,Title,Status,Severity,Client,Assignee,Alerts,Tags,Created');
    expect(lines[1]).toBe('INC-7,"Takeover, Acme",open,critical,Acme,Hal,2,bec; m365,2026-11-08T10:00:00Z');
  });
});
