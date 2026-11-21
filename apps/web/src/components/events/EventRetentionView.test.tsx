import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));
vi.mock('@/lib/api', () => ({ msspApi: { listChildren: async () => [{ id: 'c1', name: 'Acme Dental' }, { id: 'c2', name: 'Birch Law' }] } }));

import { EventRetentionView, asValue } from './EventRetentionView';

const ok = (body: unknown) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
afterEach(() => {
  cleanup();
  authFetch.mockReset();
  vi.restoreAllMocks();
});
const view = () =>
  render(
    <SWRConfig value={{ provider: () => new Map() }}>
      <EventRetentionView />
    </SWRConfig>,
  );

describe('data retention', () => {
  it('turns a choice into the value saved', () => {
    expect(asValue('infinite')).toBe('infinite');
    expect(asValue('7')).toBe(7);
  });

  it('shows what is set, saves the choice for a client and says nothing was deleted', async () => {
    const saved: unknown[] = [];
    authFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        saved.push(JSON.parse(String(init.body)));
        return ok({});
      }
      return ok({ default: 'infinite', clients: { c1: 3 }, choices: [1, 3, 5, 7, 10] });
    });
    view();
    const acme = (await screen.findByLabelText('Retention for Acme Dental')) as HTMLSelectElement;
    expect(acme.value).toBe('3');
    expect((screen.getByLabelText('Retention for Birch Law') as HTMLSelectElement).value).toBe('infinite');
    await userEvent.selectOptions(screen.getByLabelText('Retention for Birch Law'), '7');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Saved. Nothing was deleted.')).toBeInTheDocument();
    expect(saved).toEqual([{ default: 'infinite', clients: { c1: 3, c2: 7 } }]);
  });

  it('previews what is past retention and deletes only after a confirmation, naming the number', async () => {
    const posts: unknown[] = [];
    authFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith('/preview')) return ok({ by_client: { c1: 4, none: 2 }, total: 6 });
      if (init?.method === 'POST') {
        posts.push(JSON.parse(String(init.body)));
        return ok({ deleted: 6 });
      }
      return ok({ default: 'infinite', clients: {}, choices: [1, 3, 5, 7, 10] });
    });
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
    view();
    await screen.findByLabelText('Retention for Acme Dental');
    await userEvent.click(screen.getByRole('button', { name: 'Look' }));
    expect(await screen.findByText('Acme Dental: 4')).toBeInTheDocument();
    expect(screen.getByText('Events about no client: 2')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Delete these 6 events' }));
    expect(posts).toEqual([]);
    await userEvent.click(screen.getByRole('button', { name: 'Delete these 6 events' }));
    expect(await screen.findByText('Deleted 6 events.')).toBeInTheDocument();
    expect(posts).toEqual([{ confirm: 6 }]);
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(String(confirm.mock.calls[0]![0])).toContain('6 stored events');
  });

  it('says so when nothing is past retention and when the number changed', async () => {
    authFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith('/preview')) return ok({ by_client: { c1: 1 }, total: 1 });
      if (init?.method === 'POST') return Promise.resolve({ ok: false, status: 409, json: () => Promise.resolve({ detail: '3 events are past retention now, not 1; look at the preview again.' }) });
      return ok({ default: 'infinite', clients: {}, choices: [] });
    });
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    view();
    await screen.findByLabelText('Retention for Acme Dental');
    await userEvent.click(screen.getByRole('button', { name: 'Look' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Delete these 1 events' }));
    expect(await screen.findByText(/3 events are past retention now/)).toBeInTheDocument();
  });
});
