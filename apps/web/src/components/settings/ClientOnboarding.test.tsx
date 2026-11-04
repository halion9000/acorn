import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { ClientOnboarding } from './ClientOnboarding';

const steps = (done: boolean[]) => ['tools', 'devices', 'people', 'checks', 'alerts'].map((key, i) => ({ key, label: key, done: done[i], detail: `${key} detail` }));
const show = () =>
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <ClientOnboarding />
    </SWRConfig>,
  );

beforeEach(() => authFetch.mockReset());

describe('ClientOnboarding', () => {
  it('shows each client with each step done or to do and the next thing to do', async () => {
    authFetch.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve([
          { client_id: 'a', client_name: 'Acme', steps: steps([true, false, false, false, false]), done: 1, total: 5, percent: 20, next_step: 'No device has reported yet.', first_data_at: null },
          { client_id: 'b', client_name: 'Zed Co', steps: steps([true, true, true, true, true]), done: 5, total: 5, percent: 100, next_step: null, first_data_at: null },
        ]),
    });
    show();
    expect(await screen.findByText('Acme')).toBeInTheDocument();
    expect(screen.getByText('No device has reported yet.')).toBeInTheDocument();
    expect(screen.getByText('Nothing: all five are in place.')).toBeInTheDocument();
    expect(screen.getAllByText('Done')).toHaveLength(6);
    expect(screen.getAllByText('To do')).toHaveLength(4);
    expect(screen.getByText(/1 of 2 clients still have a step to do/)).toBeInTheDocument();
  });
  it('says when it cannot load', async () => {
    authFetch.mockResolvedValue({ ok: false, status: 500, json: () => Promise.resolve({}) });
    show();
    expect(await screen.findByText('Could not load this page.')).toBeInTheDocument();
  });
});

const CSV = ['Client,Percent', 'Acme,100', ''].join('\n');

describe('exporting the table', () => {
  const rows = [{ client_id: 'a', client_name: 'Acme', steps: steps([true, true, true, true, true]), done: 5, total: 5, percent: 100, next_step: null, first_data_at: null }];

  it('asks the server for the file and hands it to the browser as a download', async () => {
    const created: Blob[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    (URL as unknown as { createObjectURL: (b: Blob) => string }).createObjectURL = (b: Blob) => (created.push(b), 'blob:x');
    (URL as unknown as { revokeObjectURL: (u: string) => void }).revokeObjectURL = () => {};
    authFetch.mockImplementation((url?: string) =>
      String(url).endsWith('/export.csv') ? Promise.resolve({ ok: true, text: () => Promise.resolve(CSV) }) : Promise.resolve({ ok: true, json: () => Promise.resolve(rows) }),
    );
    show();
    await screen.findByText('Acme');
    await userEvent.click(screen.getByRole('button', { name: 'Export CSV' }));
    await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
    expect(authFetch).toHaveBeenCalledWith('/api/v1/client-onboarding/export.csv');
    expect(await created[0]!.text()).toBe(CSV);
    click.mockRestore();
  });

  it('says so when the export fails', async () => {
    authFetch.mockImplementation((url?: string) => (String(url).endsWith('/export.csv') ? Promise.resolve({ ok: false, status: 403, text: () => Promise.resolve('') }) : Promise.resolve({ ok: true, json: () => Promise.resolve(rows) })));
    show();
    await screen.findByText('Acme');
    await userEvent.click(screen.getByRole('button', { name: 'Export CSV' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Export failed (403)');
  });
});

