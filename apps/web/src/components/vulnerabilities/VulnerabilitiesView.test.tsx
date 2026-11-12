import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ list: vi.fn() }));
const mssp = vi.hoisted(() => ({ listChildren: vi.fn() }));
vi.mock('@/lib/api', async (original) => ({ ...(await original<typeof import('@/lib/api')>()), alertsApi: { list: api.list }, msspApi: mssp }));
vi.mock('next/link', () => ({ default: ({ children, href, ...rest }: { children: React.ReactNode; href: string }) => <a href={href} {...rest}>{children}</a> }));

// The per-vulnerability list has its own tests; here it is a marker that shows which client it was given.
vi.mock('./VulnerabilityLines', () => ({ VulnerabilityLines: ({ clientId }: { clientId: string }) => <div data-testid="lines-stub" data-client={clientId} /> }));

import { VulnerabilitiesView, sortFindings, toolOf } from './VulnerabilitiesView';

const alert = (over: Record<string, unknown> = {}) => ({
  id: 'a1', title: 'Many machines at this client are missing patches', description: '10 of 40 devices are patch-compliant in ThreatMate (25%)', severity: 'high', status: 'new', source: 'aisoc-checks', tenantId: 't', clientName: 'Acme', tags: ['posture-change', 'threatmate', 'threatmate_patching'],
  createdAt: '2026-11-08T10:00:00Z', updatedAt: '2026-11-08T10:00:00Z', ...over,
});
const show = () => render(<SWRConfig value={{ provider: () => new Map() }}><VulnerabilitiesView /></SWRConfig>);

beforeEach(() => { api.list.mockReset(); mssp.listChildren.mockReset(); mssp.listChildren.mockResolvedValue([]); });

describe('VulnerabilitiesView', () => {
  it('asks for the open alerts of the vulnerability category, and each row names the client, the finding and the tool and links to that alert', async () => {
    api.list.mockResolvedValue({ alerts: [alert(), alert({ id: 'a2', severity: 'critical', title: 'Past end of life', clientName: 'Beta' })], total: 2 });
    show();
    const row = await screen.findByTestId('vuln-a1');
    expect(api.list).toHaveBeenCalledWith(expect.objectContaining({ category: 'vulnerability', status: 'open' }));
    expect(row).toHaveTextContent('Acme');
    expect(row).toHaveTextContent('10 of 40 devices are patch-compliant');
    expect(row).toHaveTextContent('ThreatMate');
    expect(row.querySelector('a')).toHaveAttribute('href', '/alerts/a1');
    expect(screen.getByTestId('vulnerabilities-summary')).toHaveTextContent('2 open: 1 critical · 1 high');
  });

  it('Export CSV saves the findings shown, worst first, under a dated file name', async () => {
    const blobs: Blob[] = [];
    Object.assign(URL, { createObjectURL: vi.fn((b: Blob) => { blobs.push(b); return 'blob:v'; }), revokeObjectURL: vi.fn() });
    const names: string[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { names.push(this.download); });
    api.list.mockResolvedValue({ alerts: [alert(), alert({ id: 'a2', severity: 'critical', title: 'Past end of life', clientName: 'Beta' })], total: 2 });
    show();
    await userEvent.click(await screen.findByRole('button', { name: 'Export CSV' }));
    expect(names[0]).toMatch(/^vulnerabilities-\d{4}-\d{2}-\d{2}\.csv$/);
    const lines = (await blobs[0].text()).replace('\uFEFF', '').split('\r\n');
    expect(lines[1]).toContain('critical,Beta,Past end of life');
    expect(lines[2]).toContain('high,Acme,Many machines at this client are missing patches');
    click.mockRestore();
  });

  it('lists the worst first, and says so when there are none or the list cannot load', async () => {
    api.list.mockResolvedValue({ alerts: [], total: 0 });
    const { unmount } = show();
    expect(await screen.findByTestId('vulnerabilities-empty')).toBeInTheDocument();
    unmount();
    api.list.mockRejectedValue(new Error('503'));
    show();
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be loaded: 503');
  });

  it('opens on all clients as one list, with no wall of per-client counts above it', async () => {
    api.list.mockResolvedValue({ alerts: [alert({ tenantId: 't1', clientName: 'Acme' }), alert({ id: 'a2', tenantId: 't2', clientName: 'Beta', severity: 'critical' }), alert({ id: 'a3', tenantId: 't1', clientName: 'Acme' })], total: 3 });
    show();
    expect(await screen.findByTestId('vulnerabilities-summary')).toHaveTextContent('3 open');
    expect(api.list).toHaveBeenCalledWith(expect.not.objectContaining({ clientId: expect.anything() }));
    expect(screen.queryByTestId('vulnerabilities-by-client')).toBeNull();
    expect(screen.queryByRole('button', { name: /Acme: 2/ })).toBeNull();
    expect(screen.getByTestId('vulnerabilities')).toHaveTextContent('pick one above to narrow it');
  });

  it('puts the line-per-vulnerability list above the alerts, for all clients until one is picked', async () => {
    api.list.mockResolvedValue({ alerts: [alert()], total: 1 });
    show();
    const row = await screen.findByTestId('vuln-a1');
    const lines = screen.getByTestId('lines-stub');
    expect(lines).toHaveAttribute('data-client', '');
    expect(lines.compareDocumentPosition(row) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole('heading', { level: 2, name: 'Alerts raised' })).toBeInTheDocument();
  });

  it('sortFindings puts critical before high and newer before older; toolOf reads the tool from the tags', () => {
    const sorted = sortFindings([alert({ id: 'old', createdAt: '2026-11-01T00:00:00Z' }), alert({ id: 'crit', severity: 'critical' }), alert({ id: 'new', createdAt: '2026-11-09T00:00:00Z' })] as never);
    expect(sorted.map((a) => a.id)).toEqual(['crit', 'new', 'old']);
    expect(toolOf(alert() as never)).toBe('ThreatMate');
  });
});

describe('fix-time targets', () => {
  const old = (hours: number) => new Date(Date.now() - hours * 3_600_000).toISOString();

  it('says how long each finding has to be fixed, marks the late ones, counts them, and can show only those', async () => {
    api.list.mockResolvedValue({
      alerts: [
        alert({ id: 'late', severity: 'critical', title: 'Late one', createdAt: old(10) }),
        alert({ id: 'fresh', severity: 'high', title: 'Fresh one', createdAt: old(1) }),
        alert({ id: 'none', severity: 'info', title: 'No clock', createdAt: old(900) }),
      ],
      total: 3,
    });
    show();
    expect(await screen.findByTestId('vuln-target-late')).toHaveTextContent('Past its 4 hours target');
    expect(screen.getByTestId('vuln-target-fresh')).toHaveTextContent('Fix within 1 day');
    expect(screen.queryByTestId('vuln-target-none')).toBeNull();
    expect(screen.getByTestId('vulnerabilities-late')).toHaveTextContent('1 past their fix target');
    expect(screen.getByTestId('vulnerabilities-late').getAttribute('title')).toMatch(/critical 4 hours, high 24 hours, medium 5 days, low 14 days/);
    await userEvent.click(screen.getByRole('checkbox', { name: /past target only/i }));
    expect(screen.getByTestId('vuln-late')).toBeInTheDocument();
    expect(screen.queryByTestId('vuln-fresh')).toBeNull();
  });

  it('shows no late count or toggle when nothing is past its target', async () => {
    api.list.mockResolvedValue({ alerts: [alert({ severity: 'high', createdAt: old(1) })], total: 1 });
    show();
    await screen.findByTestId('vuln-a1');
    expect(screen.queryByTestId('vulnerabilities-late')).toBeNull();
    expect(screen.queryByRole('checkbox')).toBeNull();
  });
});

describe('the last eight weeks', () => {
  it('loads every vulnerability alert only when asked, and shows raised and closed per week with a sentence', async () => {
    const now = Date.now();
    const iso = (daysAgo: number) => new Date(now - daysAgo * 86_400_000).toISOString();
    api.list.mockImplementation(async (f: { pageSize?: number; status?: string }) =>
      f.status === 'open'
        ? { alerts: [alert()], total: 1 }
        : { alerts: [alert({ id: 't1', createdAt: iso(0) }), alert({ id: 't2', createdAt: iso(0), resolvedAt: iso(0), status: 'resolved' }), alert({ id: 't3', createdAt: iso(400) })], total: 3 },
    );
    show();
    await screen.findByTestId('vuln-a1');
    expect(api.list).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole('button', { name: 'Show the last 8 weeks' }));
    const box = await screen.findByTestId('vulnerabilities-trend');
    await waitFor(() => expect(box).toHaveTextContent('Over these 8 weeks 2 were raised and 1 closed: 1 more open than at the start.'));
    expect(box.querySelectorAll('tbody tr')).toHaveLength(8);
    expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ category: 'vulnerability', pageSize: 200 }));
    expect(api.list.mock.calls.at(-1)?.[0]).not.toHaveProperty('status');
  });
});
