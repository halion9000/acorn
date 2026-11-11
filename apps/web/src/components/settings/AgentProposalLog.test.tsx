import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ list: vi.fn(), setOutcome: vi.fn() }));
vi.mock('@/lib/api', async (original) => ({ ...(await original<typeof import('@/lib/api')>()), agentProposalsApi: api }));

import { AgentProposalLog } from './AgentProposalLog';

const show = () => render(<SWRConfig value={{ provider: () => new Map() }}><AgentProposalLog /></SWRConfig>);
const row = (over = {}) => ({
  id: 'p1', agent: 'cipher', action_type: 'close-as-false-positive', target: 'alert 42', summary: 'Looks benign', rung: 'shadow', evidence: [{ label: 'the alert', url: 'https://x/a/42' }, { label: 'sign-in log' }],
  confidence: 0.8, approval_id: null, outcome: 'none', outcome_note: null, outcome_at: null, created_at: '2026-11-09T00:00:00Z', ...over,
});
const list = (items: unknown[], unreviewed = 0) => ({ items, summary: { total: items.length, by_rung: {}, by_outcome: {}, shadow_unreviewed: unreviewed } });

beforeEach(() => { api.list.mockReset(); api.setOutcome.mockReset(); });

describe('AgentProposalLog', () => {
  it('asks the server for one agent or one outcome when chosen, keeps every agent in the choice, and says what it asked', async () => {
    const withAgents = (items: unknown[]) => ({ items, summary: { total: items.length, by_rung: {}, by_outcome: {}, shadow_unreviewed: 0, by_agent: { cipher: { total: 2 }, iris: { total: 1 } } } });
    api.list.mockResolvedValue(withAgents([row(), row({ id: 'p2', agent: 'iris' })]));
    const user = userEvent.setup();
    show();
    await screen.findByTestId('proposal-p1');
    expect(api.list).toHaveBeenLastCalledWith(undefined, { agent: '', outcome: '' });
    api.list.mockResolvedValue({ items: [row()], summary: { total: 1, by_rung: {}, by_outcome: {}, shadow_unreviewed: 0, by_agent: { cipher: { total: 1 } } } });
    await user.selectOptions(screen.getByLabelText('Agent'), 'cipher');
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith(undefined, { agent: 'cipher', outcome: '' }));
    expect(screen.getByRole('option', { name: 'iris' })).toBeInTheDocument(); // still offered although the filtered answer no longer names it
    await user.selectOptions(screen.getByLabelText('Outcome'), 'rejected');
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith(undefined, { agent: 'cipher', outcome: 'rejected' }));
  });

  it('saves the rows shown as a CSV file, and the button is off when there is nothing to save', async () => {
    const blobs: Blob[] = [];
    Object.assign(URL, { createObjectURL: vi.fn((b: Blob) => { blobs.push(b); return 'blob:p'; }), revokeObjectURL: vi.fn() });
    const names: string[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { names.push(this.download); });
    api.list.mockResolvedValue(list([row()]));
    const user = userEvent.setup();
    const first = show();
    await user.click(await screen.findByRole('button', { name: 'Export CSV' }));
    expect(names[0]).toMatch(/^agent-proposals-\d{4}-\d{2}-\d{2}\.csv$/);
    const text = await blobs[0].text();
    expect(text).toContain('cipher,close-as-false-positive,alert 42,Looks benign,Would have done (shadow)');
    first.unmount();
    api.list.mockResolvedValue(list([]));
    show();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Export CSV' })).toBeDisabled());
    click.mockRestore();
  });

  it('shows what the agent proposed, that a shadow row did nothing, its evidence as links, and how many await a verdict', async () => {
    api.list.mockResolvedValue(list([row()], 1));
    show();
    const li = await screen.findByTestId('proposal-p1');
    expect(li).toHaveTextContent('cipher · close-as-false-positive · alert 42');
    expect(li).toHaveTextContent('Would have done (nothing happened) · Not yet judged · 80% sure');
    expect(screen.getByRole('link', { name: 'the alert' })).toHaveAttribute('href', 'https://x/a/42');
    expect(li).toHaveTextContent('sign-in log');
    expect(screen.getByTestId('proposals')).toHaveTextContent('1 shadow row still waiting for a verdict');
  });

  it('records a verdict from a person and reloads; a judged row has no buttons', async () => {
    api.list.mockResolvedValueOnce(list([row()], 1)).mockResolvedValue(list([row({ outcome: 'rejected' })], 0));
    api.setOutcome.mockResolvedValue({});
    show();
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Reject' }));
    expect(api.setOutcome).toHaveBeenCalledWith('p1', 'rejected');
    await waitFor(() => expect(screen.getByTestId('proposal-p1')).toHaveTextContent('Rejected'));
    expect(screen.queryByRole('button', { name: 'Reject' })).toBeNull();
  });

  it('switches to the last 24 hours, asks for that window, and sums what the agents did on their own', async () => {
    api.list.mockResolvedValue({ items: [row()], summary: { total: 4, by_rung: { shadow: 1, suggest: 0, ask: 1, act_tell: 1, act_quiet: 1 }, by_outcome: {}, shadow_unreviewed: 1 } });
    show();
    await screen.findByTestId('proposal-p1');
    expect(api.list).toHaveBeenLastCalledWith(undefined, { agent: '', outcome: '' });
    await userEvent.setup().click(screen.getByRole('button', { name: 'Last 24 hours' }));
    expect(await screen.findByTestId('proposals-daily')).toHaveTextContent('In the last 24 hours: 2 done on their own, 1 recorded as would-have-done, 1 asked for approval, 0 suggested.');
    expect(api.list).toHaveBeenLastCalledWith(24, { agent: '', outcome: '' });
  });

  it('shows a scorecard row for each agent: what it logged, did on its own, only recorded, and how people judged it', async () => {
    api.list.mockResolvedValue({ items: [row()], summary: { total: 5, by_rung: {}, by_outcome: {}, shadow_unreviewed: 0, by_agent: { cipher: { total: 4, acted: 2, shadow: 1, asked: 1, suggested: 0, accepted: 1, edited: 1, rejected: 1, expired: 0 }, jax: { total: 1, acted: 0, shadow: 0, asked: 0, suggested: 1, accepted: 0, edited: 0, rejected: 0, expired: 1 } } } });
    show();
    const cipher = await screen.findByTestId('scorecard-cipher');
    expect(cipher).toHaveTextContent('cipher42121');
    expect(screen.getByTestId('scorecard-jax')).toHaveTextContent('jax10000');
  });

  it('says so when the verdict cannot be saved, and when there is nothing logged or the log cannot load', async () => {
    api.list.mockResolvedValue(list([row()], 1));
    api.setOutcome.mockRejectedValue(new Error('403 sign in as a person'));
    show();
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Agree' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('403 sign in as a person');
  });

  it('shows an empty message, and an error line when the log fails to load', async () => {
    api.list.mockResolvedValue(list([]));
    const { unmount } = show();
    expect(await screen.findByTestId('proposals-empty')).toBeInTheDocument();
    unmount();
    api.list.mockRejectedValue(new Error('boom'));
    show();
    expect(await screen.findByTestId('proposals-error')).toBeInTheDocument();
  });
});
