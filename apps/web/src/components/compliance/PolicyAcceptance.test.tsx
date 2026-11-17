import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { PolicyAcceptance, acceptanceSummary, parseEmails, type Acceptance } from './PolicyAcceptance';

const data: Acceptance = {
  version: 2,
  accepted: [{ email: 'ann@x.com', name: 'Ann', version: 2, accepted_on: '2026-11-01', recorded_by: 'hal@x' }],
  pending: [{ email: 'bob@x.com', name: 'Bob', older_version: 1 }, { email: 'cy@x.com', name: null, older_version: null }],
  others: [{ email: 'gone@x.com', name: null, version: 2, accepted_on: '2026-10-01', recorded_by: null }],
  share: 0.333,
};
const json = (b: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(b), { status }));

describe('Policy acceptance', () => {
  it('parses pasted addresses once each and drops what is not an address', () => {
    expect(parseEmails('Ann@x.com, bob@x.com;\nann@x.com nope')).toEqual(['ann@x.com', 'bob@x.com']);
  });
  it('summarizes the share and an empty roster', () => {
    expect(acceptanceSummary(data)).toBe('1 of 3 accepted version 2 (33%)');
    expect(acceptanceSummary({ ...data, accepted: [], pending: [], share: null })).toMatch(/No active people/);
  });
  it('lists who is pending, records one person, and records pasted addresses', async () => {
    const user = userEvent.setup();
    const scoped = vi.fn((_u: string, init?: RequestInit) => (init?.method === 'POST' ? json(data, 201) : json(data)));
    render(<PolicyAcceptance itemId="i1" scoped={scoped} />);
    expect(await screen.findByTestId('acceptance-summary')).toHaveTextContent('1 of 3 accepted version 2');
    expect(screen.getByLabelText('Not yet accepted')).toHaveTextContent('accepted version 1 only');
    expect(screen.getByText(/Also recorded, not in the people list: gone@x.com/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Record that bob@x.com accepted' }));
    await waitFor(() => expect(JSON.parse(scoped.mock.calls.find(([, i]) => i?.method === 'POST')![1]!.body as string)).toEqual({ emails: ['bob@x.com'] }));
    await user.type(screen.getByLabelText(/Record several at once/), 'cy@x.com, dee@x.com');
    await user.click(screen.getByRole('button', { name: 'Record 2 accepted' }));
    await waitFor(() => expect(scoped.mock.calls.filter(([, i]) => i?.method === 'POST')).toHaveLength(2));
  });
  it('says why when it is refused', async () => {
    const user = userEvent.setup();
    const scoped = vi.fn((_u: string, init?: RequestInit) => (init?.method === 'POST' ? json({ detail: 'That policy has no such version.' }, 422) : json(data)));
    render(<PolicyAcceptance itemId="i1" scoped={scoped} />);
    await user.click(await screen.findByRole('button', { name: 'Record that cy@x.com accepted' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('no such version');
  });
});
