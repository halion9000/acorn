import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ list: vi.fn(), create: vi.fn(), preview: vi.fn(), review: vi.fn(), revoke: vi.fn(), toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/lib/api', async (original) => ({ ...(await original<typeof import('@/lib/api')>()), clientStatusLinksApi: { list: api.list, create: api.create, preview: api.preview, review: api.review, revoke: api.revoke } }));
vi.mock('react-hot-toast', () => ({ default: api.toast }));

import { ClientStatusLinks } from './ClientStatusLinks';

const show = () => render(<SWRConfig value={{ provider: () => new Map() }}><ClientStatusLinks /></SWRConfig>);
const link = (over = {}) => ({ id: 'l1', client_id: 'c1', client_name: 'Acme', label: '', created_at: '2026-11-01T00:00:00Z', expires_at: '2027-02-01T00:00:00Z', reviewed_at: null, revoked_at: null, last_opened_at: null, state: 'not reviewed', ...over });

beforeEach(() => {
  for (const f of [api.list, api.create, api.preview, api.review, api.revoke, api.toast.success, api.toast.error]) f.mockReset();
  api.list.mockResolvedValue({ links: [], clients: [{ id: 'c1', name: 'Acme' }, { id: 'c2', name: 'Beta' }], default_days: 90 });
});

describe('ClientStatusLinks', () => {
  it('makes a link for the chosen client and shows its secret once with a warning that it does nothing until approved', async () => {
    api.create.mockResolvedValue({ ...link(), token: 'SECRETTOKEN' });
    const user = userEvent.setup();
    show();
    expect(await screen.findByTestId('status-links-empty')).toBeInTheDocument();
    await user.selectOptions(screen.getByRole('combobox'), 'c2');
    await user.click(screen.getByRole('button', { name: 'Make a link' }));
    await waitFor(() => expect(api.create).toHaveBeenCalledWith({ client_id: 'c2', label: '', days: 90 }));
    const box = await screen.findByTestId('status-secret');
    expect(box).toHaveTextContent('/status/SECRETTOKEN');
    expect(box).toHaveTextContent('shown once');
    expect(box).toHaveTextContent('does nothing until you approve');
  });

  it('previews exactly what the client sees, approves the wording only while unreviewed, and revokes', async () => {
    api.list.mockResolvedValue({ links: [link()], clients: [{ id: 'c1', name: 'Acme' }], default_days: 90 });
    api.preview.mockResolvedValue({
      client_name: 'Acme',
      generated_at: null,
      devices: { total: 50, protected: 45, percent: 90 },
      people: null,
      alerts: { open: 12, being_worked_on: 7 },
      tools: ['Managed endpoint detection (Huntress)'],
      copy: { title: 'Your security status', intro: 'intro', devices: 'Computers with endpoint protection', people: 'People protected', alerts_open: 'Security alerts open now', alerts_handled: 'of those, already being worked on by your provider', tools: 'Protections in place', footer: 'foot' },
    });
    api.review.mockResolvedValue({});
    api.revoke.mockResolvedValue({});
    const user = userEvent.setup();
    show();
    await screen.findByTestId('status-link-l1');
    await user.click(screen.getByRole('button', { name: 'Preview' }));
    const p = await screen.findByTestId('status-preview');
    expect(p).toHaveTextContent('90% (45 of 50)');
    expect(p).toHaveTextContent('People protected: not available yet');
    expect(p).toHaveTextContent('12, 7 of those, already being worked on by your provider');
    await user.click(screen.getByRole('button', { name: 'Approve wording' }));
    await waitFor(() => expect(api.review).toHaveBeenCalledWith('l1'));
    await user.click(screen.getByRole('button', { name: 'Revoke' }));
    await waitFor(() => expect(api.revoke).toHaveBeenCalledWith('l1'));
  });

  it('offers no approve button for a link that is already approved', async () => {
    api.list.mockResolvedValue({ links: [link({ reviewed_at: '2026-11-02T00:00:00Z', state: 'live' })], clients: [{ id: 'c1', name: 'Acme' }], default_days: 90 });
    show();
    await screen.findByTestId('status-link-l1');
    expect(screen.queryByRole('button', { name: 'Approve wording' })).toBeNull();
  });
});
