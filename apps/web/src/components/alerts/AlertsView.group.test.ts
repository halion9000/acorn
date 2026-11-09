import { describe, expect, it } from 'vitest';
import type { Alert } from '@/lib/api';
import { groupAlerts } from './AlertsView';

const a = (id: string, over: Partial<Alert> = {}) => ({ id, title: id, ...over }) as unknown as Alert;

describe('groupAlerts', () => {
  const alerts = [
    a('1', { device: 'PC-1', affectedUsers: ['Amy@x.com'] }),
    a('2', { device: 'pc-1', affectedUsers: ['bob@x.com'] }),
    a('3', { device: 'PC-2', affectedUsers: ['amy@x.com'] }),
    a('4', {}),
    a('5', { affectedHosts: ['PC-2'], affectedUsers: ['amy@x.com', 'bob@x.com'] }),
  ];
  it('with no grouping is one list with no heading, in the same order', () => {
    expect(groupAlerts(alerts, 'none')).toEqual([{ key: null, alerts }]);
  });
  it('by device gathers the same machine whatever the letter case, the biggest first, the unnamed last', () => {
    const g = groupAlerts(alerts, 'device');
    expect(g.map((x) => [x.key, x.alerts.map((y) => y.id)])).toEqual([
      ['pc-1', ['1', '2']],
      ['pc-2', ['3', '5']],
      ['', ['4']],
    ]);
  });
  it('by person uses the first person an alert names and puts alerts naming nobody last', () => {
    const g = groupAlerts(alerts, 'person');
    expect(g.map((x) => [x.key, x.alerts.map((y) => y.id)])).toEqual([
      ['amy@x.com', ['1', '3', '5']],
      ['bob@x.com', ['2']],
      ['', ['4']],
    ]);
  });
  it('nothing in, nothing out', () => {
    expect(groupAlerts([], 'device')).toEqual([]);
  });
});
