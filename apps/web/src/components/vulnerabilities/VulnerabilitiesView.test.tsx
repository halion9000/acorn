import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ list: vi.fn() }));
const mssp = vi.hoisted(() => ({ listChildren: vi.fn() }));
vi.mock('@/lib/api', async (original) => ({ ...(await original<typeof import('@/lib/api')>()), alertsApi: { list: api.list }, msspApi: mssp }));
vi.mock('next/link', () => ({ default: ({ children, href, ...rest }: { children: React.ReactNode; href: string }) => <a href={href} {...rest}>{children}</a> }));

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

  it('lists the worst first, and says so when there are none or the list cannot load', async () => {
    api.list.mockResolvedValue({ alerts: [], total: 0 });
    const { unmount } = show();
    expect(await screen.findByTestId('vulnerabilities-empty')).toBeInTheDocument();
    unmount();
    api.list.mockRejectedValue(new Error('503'));
    show();
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be loaded: 503');
  });

  it('sortFindings puts critical before high and newer before older; toolOf reads the tool from the tags', () => {
    const sorted = sortFindings([alert({ id: 'old', createdAt: '2026-11-01T00:00:00Z' }), alert({ id: 'crit', severity: 'critical' }), alert({ id: 'new', createdAt: '2026-11-09T00:00:00Z' })] as never);
    expect(sorted.map((a) => a.id)).toEqual(['crit', 'new', 'old']);
    expect(toolOf(alert() as never)).toBe('ThreatMate');
  });
});
