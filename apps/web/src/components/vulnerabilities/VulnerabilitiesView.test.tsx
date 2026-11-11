import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ list: vi.fn() }));
const mssp = vi.hoisted(() => ({ listChildren: vi.fn() }));
vi.mock('@/lib/api', async (original) => ({ ...(await original<typeof import('@/lib/api')>()), alertsApi: { list: api.list }, msspApi: mssp }));
vi.mock('next/link', () => ({ default: ({ children, href, ...rest }: { children: React.ReactNode; href: string }) => <a href={href} {...rest}>{children}</a> }));

import { VulnerabilitiesView, byClient, sortFindings, toolOf } from './VulnerabilitiesView';

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

  it('opens on all clients with a count for each, and pressing a client narrows the list to that client', async () => {
    api.list.mockResolvedValue({ alerts: [alert({ tenantId: 't1', clientName: 'Acme' }), alert({ id: 'a2', tenantId: 't2', clientName: 'Beta', severity: 'critical' }), alert({ id: 'a3', tenantId: 't1', clientName: 'Acme' })], total: 3 });
    show();
    const chips = await screen.findByTestId('vulnerabilities-by-client');
    expect(chips).toHaveTextContent('Beta: 1');
    expect(chips).toHaveTextContent('Acme: 2');
    expect(api.list).toHaveBeenCalledWith(expect.not.objectContaining({ clientId: expect.anything() }));
    await userEvent.setup().click(screen.getByRole('button', { name: /Acme: 2/ }));
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ clientId: 't1' })));
  });

  it('byClient counts per client, worst client first', () => {
    const rows = byClient([alert({ tenantId: 'a', clientName: 'A' }), alert({ tenantId: 'b', clientName: 'B', severity: 'critical' }), alert({ tenantId: 'a', clientName: 'A' })] as never);
    expect(rows.map((r) => [r.name, r.count, r.worst])).toEqual([['B', 1, 'critical'], ['A', 2, 'high']]);
  });

  it('sortFindings puts critical before high and newer before older; toolOf reads the tool from the tags', () => {
    const sorted = sortFindings([alert({ id: 'old', createdAt: '2026-11-01T00:00:00Z' }), alert({ id: 'crit', severity: 'critical' }), alert({ id: 'new', createdAt: '2026-11-09T00:00:00Z' })] as never);
    expect(sorted.map((a) => a.id)).toEqual(['crit', 'new', 'old']);
    expect(toolOf(alert() as never)).toBe('ThreatMate');
  });
});
