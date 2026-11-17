import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));
vi.mock('next/link', () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));

import { PolicyBanner, bannerText } from '../layout/PolicyBanner';
import { MyPoliciesView, inOrder, policyLine, type MyPolicy } from './MyPoliciesView';

const p = (over: Partial<MyPolicy> = {}): MyPolicy => ({ item_id: 'i1', title: 'Acceptable use', version: 2, body: 'Be nice.', due_on: '2026-12-01', state: 'pending', accepted_on: null, ...over });
const json = (b: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(b), { status }));

describe('My policies', () => {
  beforeEach(() => authFetch.mockReset());

  it('words each policy line and puts overdue before pending before accepted', () => {
    expect(policyLine(p())).toBe('Version 2 · due 2026-12-01');
    expect(policyLine(p({ state: 'overdue' }))).toBe('Version 2 · due 2026-12-01 (overdue)');
    expect(policyLine(p({ state: 'accepted', accepted_on: '2026-11-17' }))).toBe('Version 2 · accepted 2026-11-17');
    const order = inOrder([p({ item_id: 'a', title: 'A', state: 'accepted' }), p({ item_id: 'b', title: 'B' }), p({ item_id: 'c', title: 'C', state: 'overdue', due_on: '2026-12-09' })]);
    expect(order.map((x) => x.item_id)).toEqual(['c', 'b', 'a']);
  });

  it('shows the text of what is waiting, accepts one policy and reloads', async () => {
    const user = userEvent.setup();
    let accepted = false;
    authFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        accepted = true;
        return json(p({ state: 'accepted' }));
      }
      return json({ policies: [accepted ? p({ state: 'accepted', accepted_on: '2026-11-17' }) : p()], to_accept: accepted ? 0 : 1 });
    });
    render(<MyPoliciesView />);
    expect(await screen.findByTestId('policies-summary')).toHaveTextContent('1 to read and accept.');
    expect(screen.getByText('Be nice.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Accept Acceptable use' }));
    await waitFor(() => expect(authFetch.mock.calls.some(([u, i]) => String(u).endsWith('/api/v1/me/policies/i1/accept') && i?.method === 'POST')).toBe(true));
    expect(await screen.findByText('You have accepted everything assigned to you.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Accept/ })).toBeNull();
  });

  it('says so when nothing is assigned, and says why when it cannot load or the accept is refused', async () => {
    authFetch.mockImplementation(() => json({ policies: [], to_accept: 0 }));
    const first = render(<MyPoliciesView />);
    expect(await screen.findByTestId('no-policies')).toBeInTheDocument();
    first.unmount();
    authFetch.mockImplementation(() => json({}, 503));
    const second = render(<MyPoliciesView />);
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be loaded (503)');
    second.unmount();
    const user = userEvent.setup();
    authFetch.mockImplementation((_u: string, init?: RequestInit) => (init?.method === 'POST' ? json({ detail: 'That policy is not assigned to you.' }, 404) : json({ policies: [p()] })));
    render(<MyPoliciesView />);
    await user.click(await screen.findByRole('button', { name: /Accept/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('not assigned to you');
  });
});

describe('the policy banner', () => {
  beforeEach(() => authFetch.mockReset());

  it('says how many are waiting and how many are overdue, and nothing when none are', () => {
    expect(bannerText({ to_accept: 0, overdue: 0 })).toBeNull();
    expect(bannerText({ to_accept: 1, overdue: 0 })).toBe('You have 1 policy to read and accept.');
    expect(bannerText({ to_accept: 3, overdue: 2 })).toBe('You have 3 policies to read and accept, 2 overdue.');
  });

  it('shows a link above the pages when something is waiting, and nothing otherwise or when it cannot be read', async () => {
    authFetch.mockImplementation(() => json({ policies: [p(), p({ item_id: 'z', state: 'accepted' })] }));
    const first = render(<PolicyBanner />);
    expect(await screen.findByTestId('policy-banner')).toHaveTextContent('You have 1 policy to read and accept.');
    expect(screen.getByRole('link', { name: 'Open My policies' })).toHaveAttribute('href', '/my-policies');
    first.unmount();
    authFetch.mockImplementation(() => json({ policies: [p({ state: 'accepted' })] }));
    const second = render(<PolicyBanner />);
    await waitFor(() => expect(authFetch).toHaveBeenCalledTimes(2));
    expect(second.container.querySelector('[data-testid="policy-banner"]')).toBeNull();
    second.unmount();
    authFetch.mockImplementation(() => json({}, 500));
    const third = render(<PolicyBanner />);
    await waitFor(() => expect(authFetch).toHaveBeenCalledTimes(3));
    expect(third.container.querySelector('[data-testid="policy-banner"]')).toBeNull();
  });
});
