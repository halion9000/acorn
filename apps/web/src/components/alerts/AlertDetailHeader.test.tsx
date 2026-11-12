import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { SWRConfig } from 'swr';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }), useSearchParams: () => new URLSearchParams(), usePathname: () => '/alerts/a1' }));

const LONG_TITLE = "Microsoft Defender finds vulnerabilities with a known exploit on this client's devices";

vi.mock('@/lib/api', async (original) => {
  const real = await original<typeof import('@/lib/api')>();
  const alert = {
    id: 'a1',
    title: "Microsoft Defender finds vulnerabilities with a known exploit on this client's devices",
    description: 'Text',
    severity: 'high',
    status: 'new',
    source: 'aisoc-checks',
    tenantId: 't1',
    clientName: 'Acme',
    riskScore: 0,
    createdAt: '2026-11-11T12:53:01Z',
    updatedAt: '2026-11-11T12:53:01Z',
    affectedHosts: [],
    affectedUsers: [],
    affectedIps: [],
    tags: [],
    mitreTactics: [],
    mitreTechniques: [],
    rawEvent: {},
  };
  return { ...real, alertsApi: { ...real.alertsApi, get: vi.fn().mockResolvedValue(alert) }, authFetch: vi.fn().mockResolvedValue(new Response('{}', { status: 404 })) };
});

import { AlertDetailView } from './AlertDetailView';

describe('the alert page header', () => {
  it('gives the title its own full-width row, with the actions on a wrapping row under it, never side by side', async () => {
    render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
        <AlertDetailView alertId="a1" />
      </SWRConfig>,
    );
    const title = await screen.findByRole('heading', { level: 1, name: LONG_TITLE });
    const header = screen.getByTestId('alert-header');
    const actions = screen.getByTestId('alert-actions');
    expect(header).toContainElement(title);
    expect(header).toContainElement(actions);
    // Stacked, not a row: in a row the buttons (which never shrink) left a long title a sliver of the width.
    expect(header.className.split(/\s+/)).toContain('flex-col');
    expect(header.className).not.toMatch(/justify-between/);
    expect(actions).not.toContainElement(title);
    expect(actions.className.split(/\s+/)).toContain('flex-wrap');
    expect(actions.className).not.toMatch(/shrink-0/);
    // The title comes before the actions in the page.
    expect(title.compareDocumentPosition(actions) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(actions).getByRole('combobox')).toBeInTheDocument();
  });
});
