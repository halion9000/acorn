import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const platformUpdateApi = vi.hoisted(() => ({ get: vi.fn(), start: vi.fn() }));
vi.mock('@/lib/api', async (original) => ({ ...(await original<typeof import('@/lib/api')>()), platformUpdateApi }));
const tenantState = vi.hoisted(() => vi.fn());
vi.mock('@/components/layout/TenantProvider', () => ({ useTenant: () => tenantState() }));
vi.mock('react-hot-toast', () => ({ __esModule: true, default: { success: vi.fn(), error: vi.fn() } }));

import { ApiError } from '@/lib/api';
import { SoftwareUpdatePanel, tookLabel } from './SoftwareUpdatePanel';

describe('tookLabel', () => {
  it('says seconds under a minute, minutes and seconds above it, and a dash when it was not kept', () => {
    expect(tookLabel(0)).toBe('0 s');
    expect(tookLabel(59)).toBe('59 s');
    expect(tookLabel(60)).toBe('1 min 0 s');
    expect(tookLabel(245)).toBe('4 min 5 s');
    expect(tookLabel(null)).toBe('–');
    expect(tookLabel(undefined)).toBe('–');
  });
});

const status = (over: Record<string, unknown> = {}) => ({
  available: true, state: 'idle', requested_by: null, requested_at: null, last_run_at: null, last_run_ok: null, summary: null, log: [], ...over,
});

function renderPanel() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <SoftwareUpdatePanel />
    </SWRConfig>,
  );
}

beforeEach(() => {
  Object.values(platformUpdateApi).forEach((f) => f.mockReset());
  tenantState.mockReturnValue({ viewingOther: false, home: { name: 'Live Oak IT' } });
  platformUpdateApi.get.mockResolvedValue(status());
});

describe('SoftwareUpdatePanel', () => {
  it('while viewing another tenant it offers nothing and asks for no data', async () => {
    tenantState.mockReturnValue({ viewingOther: true, home: { name: 'Live Oak IT' } });
    renderPanel();
    expect(await screen.findByTestId('viewing-other-notice')).toHaveTextContent('Return to Live Oak IT');
    expect(platformUpdateApi.get).not.toHaveBeenCalled();
  });

  it('where updating is not set up it says so and offers no button', async () => {
    platformUpdateApi.get.mockResolvedValue(status({ available: false, state: 'unavailable' }));
    renderPanel();
    expect(await screen.findByTestId('update-unavailable')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Update A.C.O.R.N' })).toBeNull();
  });

  it('asks before updating, and only then requests it', async () => {
    platformUpdateApi.start.mockResolvedValue(status({ state: 'queued', requested_by: 'hal@x.example' }));
    renderPanel();
    await userEvent.click(await screen.findByRole('button', { name: 'Update A.C.O.R.N' }));
    expect(platformUpdateApi.start).not.toHaveBeenCalled();
    await userEvent.click(await screen.findByRole('button', { name: 'Update now' }));
    await waitFor(() => expect(platformUpdateApi.start).toHaveBeenCalledTimes(1));
    expect(await screen.findByTestId('update-state')).toHaveTextContent('Waiting to start');
    expect(screen.getByRole('button', { name: 'Updating…' })).toBeDisabled();
  });

  it('shows the output of the last run and whether it worked', async () => {
    platformUpdateApi.get.mockResolvedValue(
      status({ last_run_ok: false, summary: 'ROLLED BACK to abc', log: ['[10:04:00] UPDATE FAILED at b', '[10:06:00] ROLLED BACK to abc'], last_run_at: '2026-10-31T10:06:00Z' }),
    );
    renderPanel();
    expect(await screen.findByTestId('update-state')).toHaveTextContent('Last update failed');
    expect(screen.getByTestId('update-log')).toHaveTextContent('UPDATE FAILED at b');
    expect(screen.getByTestId('update-summary')).toHaveTextContent('ROLLED BACK to abc');
  });

  it('lists earlier runs in plain words, newest first as given, and shows no table when there are none', async () => {
    platformUpdateApi.get.mockResolvedValue(
      status({
        history: [
          { at: '2026-11-10T12:00:00Z', status: 'rolled_back', ok: false, commit: 'aaa1111', mode: 'update', seconds: 245 },
          { at: '2026-11-09T10:00:00Z', status: 'ok', ok: true, commit: null, mode: 'force' },
        ],
      }),
    );
    const first = renderPanel();
    const rows = (await screen.findByTestId('update-history')).querySelectorAll('tbody tr');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('2026-11-10 12:00:00');
    expect(rows[0]).toHaveTextContent('Failed and went back to the earlier version');
    expect(rows[0]).toHaveTextContent('aaa1111');
    expect(rows[0]).toHaveTextContent('4 min 5 s');
    expect(rows[1]).toHaveTextContent('–');
    expect(rows[1]).toHaveTextContent('Rebuild');
    expect(rows[1]).toHaveTextContent('Updated');
    expect(rows[1]).toHaveTextContent('unknown');
    first.unmount();
    platformUpdateApi.get.mockResolvedValue(status());
    renderPanel();
    await screen.findByTestId('update-state');
    expect(screen.queryByTestId('update-history')).not.toBeInTheDocument();
  });

  it('a refused request shows the reason and leaves the button usable', async () => {
    platformUpdateApi.start.mockRejectedValue(new ApiError('API 409 - /x', 409, JSON.stringify({ detail: 'An update is already waiting or running.' })));
    renderPanel();
    await userEvent.click(await screen.findByRole('button', { name: 'Update A.C.O.R.N' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Update now' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('already waiting or running');
    expect(screen.getByRole('button', { name: 'Update A.C.O.R.N' })).toBeEnabled();
  });
});
