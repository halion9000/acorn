import { describe, expect, it } from 'vitest';

import { ALERT_STATUS_TABS } from '@/components/alerts/AlertsView';
import { ACT_NOW_STATUSES } from '@/components/cases/CasesView';
import { OPEN_CASE_STATUSES } from '@/components/reports/CarryOver';
import { STATUSES as REMEMBERED_ALERT_STATUSES } from '@/lib/alert-filter-memory';
import { UI_TO_BACKEND_STATUS } from '@/lib/api';

import shared from './filterValues.json';

/**
 * A filter that sends a status the server never stores shows an empty list and nothing says why. filterValues.json is the server's own list (a server test keeps it equal to what the
 * list routes match); every fixed status a page sends has to be in it.
 */
const unknown = (sent: readonly string[], known: string[]): string[] => sent.filter((v) => !known.includes(v));
const listed = (commaSeparated: string): string[] => commaSeparated.split(',');

describe('the fixed status values the pages filter on', () => {
  it('alerts: every tab and every remembered status is one the server matches', () => {
    expect(unknown(ALERT_STATUS_TABS.filter((s) => s !== 'all'), shared.alert_status)).toEqual([]);
    expect(unknown(REMEMBERED_ALERT_STATUSES, shared.alert_status)).toEqual([]);
    expect(ALERT_STATUS_TABS).toContain('all');
  });

  it('cases: every tab, the Act now board and the carry-over list ask for statuses the server matches', () => {
    for (const sent of Object.values(UI_TO_BACKEND_STATUS)) expect(unknown(listed(sent), shared.case_status)).toEqual([]);
    expect(unknown(listed(ACT_NOW_STATUSES), shared.case_status)).toEqual([]);
    expect(unknown(listed(OPEN_CASE_STATUSES), shared.case_status)).toEqual([]);
  });

  it('notices a value the server does not have', () => {
    expect(unknown(['open', 'opened'], shared.alert_status)).toEqual(['opened']);
    expect(unknown(listed('new,in-progress'), shared.case_status)).toEqual(['in-progress']);
  });
});
