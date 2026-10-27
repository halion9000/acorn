import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { SWRConfig } from 'swr';

import { FrameworkView } from './FrameworkView';

const authFetch = vi.fn();
vi.mock('@/lib/auth-session', () => ({ authFetch: (...a: unknown[]) => authFetch(...a) }));
const listChildren = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api', () => ({ msspApi: { listChildren } }));

const json = (body: unknown) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });

// Braces: a hook that RETURNS the mock would have vitest call it as a cleanup function, with no arguments.
beforeEach(() => {
  authFetch.mockReset();
  listChildren.mockReset();
  listChildren.mockResolvedValue([]);
});
afterEach(() => cleanup());

describe('FrameworkView', () => {
  it('shows each control with its evidence state and the real coverage figure', async () => {
    authFetch.mockImplementation((url: string) => {
      if (url.includes('/controls')) return json({ controls: [{ control_id: 'CC6.1', title: 'Access' }, { control_id: 'CC1.1', title: 'Competence' }] });
      if (url.includes('/report')) return json([{ total_evidence: 1, accepted: 1, pending: 0, rejected: 0, coverage_pct: 50, controls_covered: ['CC6.1'], controls_missing: ['CC1.1'] }]);
      return json([{ id: 'e1', control_id: 'CC6.1', summary: 'Account inventory: 4 active user(s)', status: 'accepted', collected_at: '2026-10-17T10:00:00Z', reviewed_by: 'hal' }]);
    });
    render(<FrameworkView framework="soc2" />);
    await waitFor(() => expect(screen.getByTestId('coverage').textContent).toContain('50% of controls have accepted evidence'));
    expect(screen.getByText('Account inventory: 4 active user(s)')).toBeTruthy();
    expect(screen.getByText('No evidence')).toBeTruthy(); // CC1.1 is never filled in for anyone
  });

  it('says plainly when the framework has no control list in this build', () => {
    render(<FrameworkView framework="some-future-framework" />);
    expect(screen.getByText(/no control list in this A.C.O.R.N build/)).toBeTruthy();
    expect(authFetch).not.toHaveBeenCalled();
  });

  it('shows an error instead of an empty page when the API refuses', async () => {
    authFetch.mockImplementation(() => Promise.resolve({ ok: false, status: 503, json: () => Promise.resolve({}) }));
    render(<FrameworkView framework="hipaa" />);
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('503'));
  });

  it('lets a person add an attestation to a control, and it waits for review before it counts', async () => {
    const posts: { url: string; body: any }[] = [];
    authFetch.mockImplementation((url: string, init?: { method?: string; body?: string }) => {
      if (init?.method === 'POST') {
        posts.push({ url, body: JSON.parse(String(init.body)) });
        return json({ id: 'new' });
      }
      if (url.includes('/controls')) return json({ controls: [{ control_id: 'CC1.1', title: 'Competence' }] });
      if (url.includes('/report')) return json([{ total_evidence: 0, accepted: 0, pending: 0, rejected: 0, coverage_pct: 0, controls_covered: [], controls_missing: ['CC1.1'] }]);
      return json([]);
    });
    render(<FrameworkView framework="soc2" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Add evidence' }));
    const add = screen.getByRole('button', { name: 'Add' });
    expect(add).toBeDisabled(); // nothing typed yet
    await user.type(screen.getByLabelText('Evidence'), 'Annual security training completed 2026-09-30');
    await user.selectOptions(screen.getByLabelText('Kind of evidence'), 'policy');
    await user.click(screen.getByRole('button', { name: 'Add' }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0].url).toBe('/api/v1/compliance/evidence');
    expect(posts[0].body).toEqual({ framework: 'SOC2', control_id: 'CC1.1', evidence_kind: 'policy', summary: 'Annual security training completed 2026-09-30', raw_payload: { source: 'manual' } });
    expect(await screen.findByText(/waits for a review below before it counts/)).toBeInTheDocument();
  });

  it('refuses a summary that is too short to mean anything', async () => {
    authFetch.mockImplementation((url: string) => {
      if (url.includes('/controls')) return json({ controls: [{ control_id: 'CC1.1', title: 'Competence' }] });
      if (url.includes('/report')) return json([]);
      return json([]);
    });
    render(<FrameworkView framework="soc2" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Add evidence' }));
    await user.type(screen.getByLabelText('Evidence'), 'ok');
    expect(screen.getByRole('button', { name: 'Add' })).toBeDisabled();
  });
});

describe('FrameworkView for a client', () => {
  const answer = (url: string) => {
    if (url.includes('/controls')) return json({ controls: [{ control_id: 'CC6.1', title: 'Access' }] });
    if (url.includes('/report')) return json([{ total_evidence: 0, accepted: 0, pending: 0, rejected: 0, coverage_pct: 0, controls_covered: [], controls_missing: ['CC6.1'] }]);
    return json([]);
  };

  it('reads and writes the own evidence of the organisation until a client is chosen, then only that of the client', async () => {
    listChildren.mockResolvedValue([{ id: 'c1', name: 'Acme Dental', mssp_role: 'client' }]);
    authFetch.mockImplementation((url: string) => answer(url));
    render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
        <FrameworkView framework="soc2" />
      </SWRConfig>,
    );
    await waitFor(() => expect(screen.getByTestId('coverage')).toBeTruthy());
    expect(authFetch.mock.calls.filter((c) => String(c[0]).includes('/evidence') || String(c[0]).includes('/report')).every((c) => !String(c[0]).includes('client_id'))).toBe(true);

    authFetch.mockClear();
    await userEvent.selectOptions(await screen.findByRole('combobox', { name: 'Client' }), 'c1');
    await waitFor(() => expect(authFetch.mock.calls.some((c) => String(c[0]).includes('/report?framework=SOC2&client_id=c1'))).toBe(true));
    expect(authFetch.mock.calls.some((c) => String(c[0]).includes('/evidence?framework=SOC2&limit=200&client_id=c1'))).toBe(true);

    authFetch.mockClear();
    await userEvent.click(screen.getByRole('button', { name: /Collect platform evidence/ }));
    await waitFor(() => expect(authFetch.mock.calls.some((c) => String(c[0]).startsWith('/api/v1/compliance/evidence/collect?client_id=c1'))).toBe(true));
  });
});

describe('a framework with many controls', () => {
  const many = [
    { control_id: 'A.5.1', title: 'Policies for information security', group: 'A.5 Organizational controls' },
    { control_id: 'A.5.2', title: 'Information security roles and responsibilities', group: 'A.5 Organizational controls' },
    ...Array.from({ length: 12 }, (_, i) => ({ control_id: `A.8.${i + 1}`, title: `Technological ${i + 1}`, group: 'A.8 Technological controls' })),
    { control_id: 'A.6.8', title: 'Information security event reporting', group: 'A.6 People controls' },
  ];
  const setup = () =>
    authFetch.mockImplementation((url: string) => {
      if (url.includes('/controls')) return json({ controls: many });
      if (url.includes('/report')) return json([{ total_evidence: 1, accepted: 1, pending: 0, rejected: 0, coverage_pct: 7, controls_covered: ['A.5.1'], controls_missing: [] }]);
      return json([{ id: 'e1', control_id: 'A.5.1', summary: 'Policy exists', status: 'accepted', collected_at: '2026-10-01T00:00:00Z', reviewed_by: 'sam' }]);
    });

  it('groups the controls under the headings of the framework and counts the accepted ones in each', async () => {
    setup();
    render(<FrameworkView framework="iso27001" />);
    const group = await screen.findByTestId('group-A.5 Organizational controls');
    expect(group.textContent).toContain('1 of 2 with accepted evidence');
    expect(screen.getByTestId('group-A.8 Technological controls').textContent).toContain('0 of 12 with accepted evidence');
    expect(screen.getByTestId('group-A.6 People controls')).toBeTruthy();
  });

  it('filters by id, title or heading, and says so when nothing matches', async () => {
    setup();
    render(<FrameworkView framework="iso27001" />);
    const box = await screen.findByRole('searchbox', { name: 'Filter controls' });
    fireEvent.change(box, { target: { value: 'event reporting' } });
    expect(screen.getByText('Information security event reporting')).toBeTruthy();
    expect(screen.queryByText('Technological 1')).toBeNull();
    fireEvent.change(box, { target: { value: 'zzzz nothing' } });
    expect(screen.getByText('No control matches that text.')).toBeTruthy();
  });

  it('has no DORA page any more', () => {
    render(<FrameworkView framework="dora" />);
    expect(screen.getByText(/no control list in this A.C.O.R.N build/)).toBeTruthy();
  });
});

describe('groupControls and matchControls', () => {
  it('keeps the API order, puts an ungrouped control under Controls, and matches case-insensitively', async () => {
    const { groupControls, matchControls } = await import('./FrameworkView');
    const list = [
      { control_id: 'x', title: 'Zed' },
      { control_id: 'a', title: 'Alpha', group: 'G1' },
      { control_id: 'b', title: 'Beta', group: 'G1' },
    ];
    expect(groupControls(list).map((g) => [g.name, g.controls.length])).toEqual([['Controls', 1], ['G1', 2]]);
    expect(matchControls(list, 'ALPHA').map((c) => c.control_id)).toEqual(['a']);
    expect(matchControls(list, 'g1').length).toBe(2);
    expect(matchControls(list, '  ').length).toBe(3);
  });
});
