import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { EASMView, lastScanText } from './EASMView';
import userEvent from '@testing-library/user-event';

const authFetch = vi.fn();
vi.mock('@/lib/auth-session', () => ({ authFetch: (...a: unknown[]) => authFetch(...a) }));

const ok = (body: unknown) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });

beforeEach(() => {
  authFetch.mockReset();
});
afterEach(() => cleanup());

describe('EASMView', () => {
  it('lists the discovered assets by type and the drift against the asset it happened on', async () => {
    authFetch.mockImplementation((url: string) =>
      url.includes('/assets')
        ? ok([
            { id: 'a1', asset_type: 'domain', value: 'example.com', first_seen: '2026-10-01T00:00:00Z', last_seen: '2026-10-17T00:00:00Z', metadata: {} },
            { id: 'a2', asset_type: 'ip', value: '8.8.8.8', first_seen: '2026-10-01T00:00:00Z', last_seen: '2026-10-17T00:00:00Z', metadata: {} },
          ])
        : ok([{ id: 'd1', external_asset_id: 'a2', drift_type: 'new_open_port', details: {}, detected_at: '2026-10-17T05:00:00Z' }]),
    );
    render(<EASMView />);
    await waitFor(() => expect(screen.getByTestId('asset-summary').textContent).toBe('2 external asset(s): 1 domain, 1 ip'));
    expect(screen.getByText('new_open_port')).toBeTruthy();
    expect(screen.getAllByText('8.8.8.8').length).toBe(2); // the asset row and the drift line
  });

  it('says there is nothing yet, rather than pretending, when no asset was discovered', async () => {
    authFetch.mockImplementation(() => ok([]));
    render(<EASMView />);
    await waitFor(() => expect(screen.getByTestId('asset-summary').textContent).toContain('No external assets discovered yet'));
  });

  it('shows the error when the API refuses', async () => {
    authFetch.mockImplementation(() => Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) }));
    render(<EASMView />);
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('500'));
  });
});

describe('IP targets', () => {
  it('splits what was typed into unique addresses', async () => {
    const { parseTargets } = await import('./EASMView');
    expect(parseTargets('203.0.113.10, 198.51.100.7\n203.0.113.10;  ')).toEqual(['203.0.113.10', '198.51.100.7']);
    expect(parseTargets('   ')).toEqual([]);
  });
});

describe('what a scan can do and how the last one went', () => {
  const status = (over: Record<string, unknown> = {}) => ({
    plan: { shodan: false, censys: false, port_check: false, sources: [], can_run: false, problem: 'Nothing is set up to discover with. Add a Shodan key.' },
    last_scan: null,
    ...over,
  });
  const serve = (st: unknown, scanResponse?: { status: number; body: unknown }) =>
    authFetch.mockImplementation((url: string, init?: { method?: string }) => {
      if (init?.method === 'POST') return Promise.resolve({ ok: (scanResponse?.status ?? 202) < 300, status: scanResponse?.status ?? 202, json: () => Promise.resolve(scanResponse?.body ?? {}) });
      if (url.includes('/status')) return ok(st);
      return ok([]);
    });

  it('says which sources are set up and what to change when none is', async () => {
    serve(status());
    render(<EASMView />);
    const box = await screen.findByTestId('scan-status');
    expect(box.textContent).toContain('set up on this server: none');
    expect(box.textContent).toContain('Add a Shodan key');
  });

  it('shows the reason the server gives when a scan cannot run, instead of "Scan started"', async () => {
    serve(status(), { status: 409, body: { detail: 'The port check is switched off on this server.' } });
    render(<EASMView />);
    await screen.findByTestId('scan-status');
    await userEvent.click(screen.getByRole('button', { name: 'Run a scan' }));
    expect(await screen.findByText('The port check is switched off on this server.')).toBeTruthy();
    expect(screen.queryByText(/Scan started/)).toBeNull();
  });

  it('describes the last scan: nothing found, found some, or failed', () => {
    expect(lastScanText(null)).toBeNull();
    expect(lastScanText({ finished_at: '2026-10-27T12:00:00Z', found: 0, changes: 0, sources: ['shodan'], error: null })).toContain('finished and found nothing');
    expect(lastScanText({ finished_at: '2026-10-27T12:00:00Z', found: 3, changes: 1, sources: ['shodan', 'censys'] })).toMatch(/using shodan and censys found 3 assets and 1 change./);
    expect(lastScanText({ finished_at: '2026-10-27T12:00:00Z', error: 'The scan failed (OSError)' })).toContain('failed: The scan failed (OSError)');
  });

  it('works against an API that has no status route', async () => {
    authFetch.mockImplementation((url: string) => (url.includes('/status') ? Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) }) : ok([])));
    render(<EASMView />);
    await waitFor(() => expect(screen.getByTestId('asset-summary')).toBeTruthy());
    expect(screen.queryByTestId('scan-status')).toBeNull();
  });
});
