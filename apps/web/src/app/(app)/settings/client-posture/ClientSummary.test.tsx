import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.fn();
vi.mock('@/lib/auth-session', () => ({ authFetch: (...a: unknown[]) => authFetch(...a) }));

import { ClientSummary } from './ClientSummary';
import type { Posture } from './ClientPosture';

const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }));

const posture: Posture = {
  client_id: 'c1',
  client_name: 'Acme Dental',
  generated_at: '2026-10-26T00:00:00Z',
  devices: { devices: 52, needs_attention: 4, stale_agents: 0, not_in_huntress: 0, offline: 0 },
  identity: { people: 30, with_mfa: 27, not_required: 0, without_mfa: 3, admins_without_mfa: 1, refreshed_at: null },
  alerts: { open: 0, critical: 0, high: 0, without_ticket: 0 },
  open_cases: 0,
  tool_checks: { slide: { checks: [{ key: 'slide_verification', status: 'not_met', evidence: 'x' }, { key: 'slide_alerts', status: 'met', evidence: 'y' }] } },
};
const labelFor = (s: string, k: string) => `${s}: ${k}`;
const recent = new Date(Date.now() - 2 * 86_400_000).toISOString();
const old = new Date(Date.now() - 40 * 86_400_000).toISOString();

beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockImplementation((url: string) => {
    if (url.includes('/score-history')) return json({ first: 70, last: 78, change: 8, rows: [{}, {}, {}, {}, {}, {}, {}] });
    if (url.includes('/check-history')) return json({ rows: [{ key: 'slide_verification', source: 'slide', status: 'not_met', previous_status: 'met', observed_at: recent }, { key: 'old_one', source: 'x', status: 'not_met', previous_status: 'met', observed_at: old }] });
    if (url.endsWith('/compare')) return json({ score: 78, fleet_average: 72, similar_average: null, similar_clients: 0 });
    if (url.includes('/billing/clients/')) return json({ rows: [{ source: 'ninjaone', item: 'Windows workstations', count: 52, change: 6 }] });
    return json({});
  });
});

describe('ClientSummary', () => {
  it('writes the weekly draft from the score, the checks and what changed in the week, and asks for no counts', async () => {
    render(<ClientSummary posture={posture} labelFor={labelFor} />);
    const box = await screen.findByRole('textbox', { name: 'Draft update' });
    const text = (box as HTMLTextAreaElement).value;
    expect(text).toContain('Acme Dental: weekly update');
    expect(text).toContain('Score: 78%, up 8 points from 70%');
    expect(text).toContain('1 check needs attention now: slide: slide_verification.');
    expect(text).toContain('Got worse in this period: slide: slide_verification.');
    expect(text).not.toContain('old_one');
    expect(authFetch.mock.calls.some((c) => String(c[0]).includes('/billing/'))).toBe(false);
  });

  it('writes the quarterly review with devices, Multi-Factor and the counts that moved', async () => {
    render(<ClientSummary posture={posture} labelFor={labelFor} />);
    await screen.findByRole('textbox', { name: 'Draft update' });
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Update period' }), '90');
    await waitFor(() => expect((screen.getByRole('textbox', { name: 'Draft update' }) as HTMLTextAreaElement).value).toContain('quarterly review'));
    const text = (screen.getByRole('textbox', { name: 'Draft update' }) as HTMLTextAreaElement).value;
    expect(text).toContain('Devices: 52, of which 4 need attention.');
    expect(text).toContain('Multi-Factor: 27 of 30 people covered');
    expect(text).toContain('Windows workstations (ninjaone) 46 to 52');
  });

  it('still writes a draft when a part is refused or empty, and the draft can be edited', async () => {
    authFetch.mockImplementation((url: string) => (url.includes('/billing/') || url.includes('/compare') ? json({}, 403) : json({})));
    render(<ClientSummary posture={posture} labelFor={labelFor} />);
    const box = (await screen.findByRole('textbox', { name: 'Draft update' })) as HTMLTextAreaElement;
    expect(box.value).toContain('No score yet');
    await userEvent.type(box, ' Edited.');
    expect(box.value).toContain('Edited.');
  });
});
