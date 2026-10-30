import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AlertRow, openDays } from './AlertsView';
import type { Alert } from '@/lib/api';

const NOW = Date.parse('2026-10-29T12:00:00Z');
const ago = (days: number) => new Date(NOW - days * 86_400_000).toISOString();
const alert = (over: Partial<Alert> = {}) =>
  ({ id: 'a1', title: 'Unexpected Country', description: '', severity: 'high', status: 'new', source: 'huntress', tenantId: 't', riskScore: 5, createdAt: ago(1), ...over }) as unknown as Alert;

describe('openDays', () => {
  it('is the whole days an unfinished alert has been open, from a week on', () => {
    expect(openDays(ago(7), 'new', NOW)).toBe(7);
    expect(openDays(ago(12.9), 'investigating', NOW)).toBe(12);
    expect(openDays(ago(6.9), 'new', NOW)).toBeNull();
  });

  it('is null for finished alerts and for dates that cannot be read', () => {
    for (const status of ['resolved', 'closed', 'false_positive', 'auto_closed']) expect(openDays(ago(30), status, NOW)).toBeNull();
    expect(openDays(undefined, 'new', NOW)).toBeNull();
    expect(openDays('not a date', 'new', NOW)).toBeNull();
  });
});

describe('the alert row age badge', () => {
  it('shows how long an old open alert has been open, and nothing on a young or a finished one', () => {
    const old = new Date(Date.now() - 10 * 86_400_000).toISOString();
    const { unmount } = render(<AlertRow alert={alert({ createdAt: old })} selected={false} onSelect={() => {}} />);
    expect(screen.getByTestId('alert-open-days')).toHaveTextContent('10d open');
    unmount();
    const young = render(<AlertRow alert={alert()} selected={false} onSelect={() => {}} />);
    expect(screen.queryByTestId('alert-open-days')).toBeNull();
    young.unmount();
    render(<AlertRow alert={alert({ createdAt: old, status: 'resolved' })} selected={false} onSelect={() => {}} />);
    expect(screen.queryByTestId('alert-open-days')).toBeNull();
  });
});
