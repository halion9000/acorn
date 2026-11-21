import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { PolicyAcceptLinks, linkLine } from './PolicyAcceptLinks';

const made = [{ id: 'l1', email: 'ann@x.com', version: 2, expires_on: '2026-12-05', state: 'open', path: '/api/v1/public/policy/TOK', url: null, emailed: false }];
const listed = [
  { ...made[0]!, path: null },
  { id: 'l2', email: 'bob@x.com', version: 2, expires_on: '2026-11-30', state: 'used', path: null, url: null, emailed: false },
];
const json = (b: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(b), { status }));

describe('Links for people without an account', () => {
  it('words each line by state', () => {
    expect(linkLine(listed[0]!)).toBe('ann@x.com · open until 2026-12-05 (version 2)');
    expect(linkLine(listed[1]!)).toBe('bob@x.com · used (version 2)');
    expect(linkLine({ ...listed[0]!, state: 'expired' })).toBe('ann@x.com · expired 2026-12-05 (version 2)');
  });

  it('makes links for pasted addresses, shows each once, and cancels an open one', async () => {
    const user = userEvent.setup();
    const scoped = vi.fn((_url: string, init?: RequestInit) => (init?.method === 'POST' ? json(made, 201) : init?.method === 'DELETE' ? Promise.resolve(new Response(null, { status: 204 })) : json(listed)));
    render(<PolicyAcceptLinks itemId="i1" scoped={scoped} />);
    expect(await screen.findByLabelText('Links made')).toHaveTextContent('bob@x.com · used');
    await user.type(screen.getByLabelText('Addresses for links'), 'ann@x.com');
    await user.click(screen.getByRole('button', { name: 'Make 1 link' }));
    expect(await screen.findByLabelText('New links')).toHaveTextContent('/api/v1/public/policy/TOK');
    const post = scoped.mock.calls.find(([, i]) => i?.method === 'POST')!;
    expect(JSON.parse(post[1]!.body as string)).toEqual({ emails: ['ann@x.com'], expires_days: 14, send: false });
    await user.click(screen.getByRole('button', { name: 'Cancel the link for ann@x.com' }));
    await waitFor(() => expect(scoped.mock.calls.some(([u, i]) => String(u).endsWith('/accept-links/l1') && i?.method === 'DELETE')).toBe(true));
    expect(screen.queryByRole('button', { name: 'Cancel the link for bob@x.com' })).toBeNull();
  });

  it('says why when making links is refused', async () => {
    const user = userEvent.setup();
    const scoped = vi.fn((_url: string, init?: RequestInit) => (init?.method === 'POST' ? json({ detail: 'E-mailing links needs PUBLIC_PAGES_BASE_URL' }, 422) : json([])));
    render(<PolicyAcceptLinks itemId="i1" scoped={scoped} />);
    await user.type(screen.getByLabelText('Addresses for links'), 'ann@x.com');
    await user.click(screen.getByRole('checkbox'));
    await user.click(screen.getByRole('button', { name: 'Make 1 link' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('PUBLIC_PAGES_BASE_URL');
  });
});
