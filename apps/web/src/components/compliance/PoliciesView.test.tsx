import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));
vi.mock('@/lib/api', () => ({
  msspApi: {
    listChildren: async () => [
      { id: 'live-oak', name: 'Live Oak IT Partners' },
      { id: 'acme', name: 'Acme Dental' },
    ],
  },
}));
vi.mock('./SecureframeRegisters', () => ({ SecureframeRegisters: () => <div data-testid="secureframe-policies" /> }));

import { PoliciesView } from './PoliciesView';

const json = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } }));
const item = (title: string) => ({ id: title, kind: 'policy', title, owner: '', notes: '', interval_days: 365, next_due: '2026-12-01', last_reviewed_at: null, state: 'ok', days_until: 30, versions: 0 });

beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockImplementation((url: string) => {
    if (url.startsWith('/api/v1/governance/templates')) return json([]);
    if (url.includes('client_id=acme')) return json([item('Acme acceptable use')]);
    if (url.startsWith('/api/v1/governance')) return json([item('Live Oak acceptable use')]);
    return json({});
  });
  window.history.replaceState(null, '', '/compliance/policies');
});

const renderView = () =>
  render(
    <SWRConfig value={{ provider: () => new Map() }}>
      <PoliciesView />
    </SWRConfig>,
  );

describe('PoliciesView', () => {
  it('has a client picker that starts on the organization own company and asks for that client', async () => {
    renderView();
    expect(await screen.findByLabelText('Client')).toHaveValue('live-oak');
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/api/v1/governance?client_id=live-oak', undefined));
    expect(await screen.findByText(/Live Oak acceptable use/)).toBeTruthy();
    expect(screen.getByTestId('secureframe-policies')).toBeTruthy();
  });

  it('shows another client its own policies, and not the organization Secureframe list', async () => {
    renderView();
    await screen.findByText(/Live Oak acceptable use/);
    await userEvent.selectOptions(await screen.findByLabelText('Client'), 'acme');
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/api/v1/governance?client_id=acme', undefined));
    expect(await screen.findByText(/Acme acceptable use/)).toBeTruthy();
    expect(screen.queryByText(/Live Oak acceptable use/)).toBeNull();
    expect(screen.queryByTestId('secureframe-policies')).toBeNull();
  });

  it('opens on the client named in the address', async () => {
    window.history.replaceState(null, '', '/compliance/policies?client=acme');
    renderView();
    expect(await screen.findByText(/Acme acceptable use/)).toBeTruthy();
    expect(screen.queryByTestId('secureframe-policies')).toBeNull();
  });
});
