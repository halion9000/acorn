import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const alertsApi = vi.hoisted(() => ({ list: vi.fn() }));
const casesApi = vi.hoisted(() => ({ list: vi.fn() }));
vi.mock('@/lib/api', () => ({ alertsApi, casesApi }));
vi.mock('next/link', () => ({ default: ({ children, href, ...rest }: { children: React.ReactNode; href: string }) => <a href={href} {...rest}>{children}</a> }));

import { CarryOver } from './CarryOver';

const alert = (id: string, severity: string, over: Record<string, unknown> = {}) => ({ id, title: `Alert ${id}`, severity, createdAt: '2026-11-10T00:00:00Z', ...over });

beforeEach(() => {
  alertsApi.list.mockReset();
  casesApi.list.mockReset();
  alertsApi.list.mockImplementation(async (f: { severity: string }) =>
    f.severity === 'critical' ? { alerts: [alert('c1', 'critical', { clientName: 'Acme' })], total: 1 } : { alerts: [alert('h1', 'high', { assignee: 'sam@example.com' })], total: 40 },
  );
  casesApi.list.mockResolvedValue({ cases: [{ id: 'k1', caseNumber: 'INC-007', title: 'Mailbox takeover', severity: 'high', status: 'in_progress', createdAt: '2026-11-09T00:00:00Z' }] });
});

describe('CarryOver', () => {
  it('reads nothing until asked, then asks only for open critical and high alerts and open cases', async () => {
    render(<CarryOver clientId="" />);
    expect(alertsApi.list).not.toHaveBeenCalled();
    expect(casesApi.list).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Show what carries over' }));
    await screen.findByTestId('carry-alert-count');
    expect(alertsApi.list.mock.calls.map((c) => [c[0].status, c[0].severity, c[0].clientId])).toEqual([
      ['open', 'critical', undefined],
      ['open', 'high', undefined],
    ]);
    expect(casesApi.list.mock.calls[0][0]).toMatchObject({ status: 'new,triaged,investigating,contained', scope: 'all' });
  });

  it('lists the critical alert first, links each one, and counts the alerts it does not list', async () => {
    render(<CarryOver clientId="" />);
    await userEvent.click(screen.getByRole('button', { name: 'Show what carries over' }));
    expect(await screen.findByTestId('carry-alert-count')).toHaveTextContent('Critical and high alerts still open: 41');
    const rows = screen.getAllByTestId('carry-alert');
    expect(rows[0]).toHaveTextContent('Alert c1 (Acme)');
    expect(rows[0]).toHaveTextContent('with nobody');
    expect(rows[1]).toHaveTextContent('with sam@example.com');
    expect(screen.getByRole('link', { name: 'Alert c1' })).toHaveAttribute('href', '/alerts/c1');
    expect(screen.getByTestId('carry-alert-more')).toHaveTextContent('and 39 more');
    expect(screen.getByTestId('carry-case')).toHaveTextContent('INC-007 Mailbox takeover, in progress');
    expect(screen.getByRole('link', { name: /INC-007/ })).toHaveAttribute('href', '/cases/k1');
  });

  it('with a client chosen it asks only for that client', async () => {
    render(<CarryOver clientId="client-9" />);
    await userEvent.click(screen.getByRole('button', { name: 'Show what carries over' }));
    await screen.findByTestId('carry-alert-count');
    expect(alertsApi.list.mock.calls.every((c) => c[0].clientId === 'client-9')).toBe(true);
    expect(casesApi.list.mock.calls[0][0].clientId).toBe('client-9');
  });

  it('copies the list as text', async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue();
    render(<CarryOver clientId="" />);
    await user.click(screen.getByRole('button', { name: 'Show what carries over' }));
    await user.click(await screen.findByRole('button', { name: 'Copy as text' }));
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument();
    expect(writeText.mock.calls[0][0]).toContain('- [critical] Alert c1 (Acme)');
    expect(writeText.mock.calls[0][0]).toContain('- and 39 more');
  });

  it('says so when the list cannot be read, and shows no list', async () => {
    alertsApi.list.mockRejectedValue(new Error('boom'));
    render(<CarryOver clientId="" />);
    await userEvent.click(screen.getByRole('button', { name: 'Show what carries over' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be read');
    expect(screen.queryByTestId('carry-alert-count')).toBeNull();
  });
});
