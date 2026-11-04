import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ list: vi.fn(), mergePeople: vi.fn(), separatePeople: vi.fn(), decisions: vi.fn(), removeDecision: vi.fn() }));
vi.mock('@/lib/api', () => ({ identitiesApi: { list: api.list, mergePeople: api.mergePeople, separatePeople: api.separatePeople, decisions: api.decisions, removeDecision: api.removeDecision } }));

import { MergePanel } from './MergePanel';

const person = { client_id: 'c1', email: 'adam@tecovas.com', display_name: 'Adam', aliases: [{ email: 'adam@tecovas.onmicrosoft.com', reason: "the same name on the client's Microsoft address" }] };
const other = { key: 'c1:bmoore@acme.com', email: 'bmoore@acme.com', display_name: 'Brandon Moore', tools: ['cipp', 'huntress'] };

beforeEach(() => {
  api.list.mockReset().mockResolvedValue({ items: [other, { ...other, key: 'self', email: person.email }] });
  api.mergePeople.mockReset().mockResolvedValue({ kind: 'merge' });
  api.separatePeople.mockReset().mockResolvedValue({ kind: 'separate' });
  api.decisions.mockReset().mockResolvedValue({ items: [] });
  api.removeDecision.mockReset().mockResolvedValue(undefined);
});

describe('MergePanel', () => {
  it('lists the shown address, each folded-in address with its reason, and a Not the same person button for each', async () => {
    const onChanged = vi.fn();
    render(<MergePanel person={person} onChanged={onChanged} />);
    expect(screen.getByText('adam@tecovas.com')).toBeInTheDocument();
    expect(screen.getByText('adam@tecovas.onmicrosoft.com')).toBeInTheDocument();
    expect(screen.getByText(/the same name on the client's Microsoft address/)).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: 'adam@tecovas.onmicrosoft.com is not the same person' }));
    await waitFor(() => expect(api.separatePeople).toHaveBeenCalledWith({ client_id: 'c1', email: 'adam@tecovas.onmicrosoft.com', from_email: 'adam@tecovas.com' }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('shows no split buttons for a person with only one address', () => {
    render(<MergePanel person={{ ...person, aliases: [] }} onChanged={vi.fn()} />);
    expect(screen.queryByRole('button', { name: /is not the same person/ })).toBeNull();
  });

  it('searches the same client, leaves the person out of their own results, asks first, and merges only on Yes', async () => {
    const onChanged = vi.fn();
    render(<MergePanel person={person} onChanged={onChanged} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Merge with another person…' }));
    await user.type(screen.getByLabelText('Find the person to merge with'), 'bmoore');
    await waitFor(() => expect(api.list).toHaveBeenCalledWith({ clientId: 'c1', search: 'bmoore', pageSize: 8 }));
    const result = await screen.findByRole('button', { name: /bmoore@acme.com/ });
    expect(screen.queryByRole('button', { name: /adam@tecovas.com · 2 tools/ })).toBeNull();
    await user.click(result);
    expect(screen.getByRole('dialog', { name: 'Merge these two?' })).toBeInTheDocument();
    expect(api.mergePeople).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'No, cancel' }));
    expect(api.mergePeople).not.toHaveBeenCalled();
    await user.click(result);
    await user.click(screen.getByRole('button', { name: 'Yes, merge' }));
    await waitFor(() => expect(api.mergePeople).toHaveBeenCalledWith({ client_id: 'c1', email: 'adam@tecovas.com', with_email: 'bmoore@acme.com' }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('does not search for fewer than two characters, and shows the refusal in the window', async () => {
    api.mergePeople.mockRejectedValue(new Error('They are already one person.'));
    render(<MergePanel person={person} onChanged={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Merge with another person…' }));
    await user.type(screen.getByLabelText('Find the person to merge with'), 'b');
    await new Promise((r) => setTimeout(r, 400));
    expect(api.list).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText('Find the person to merge with'), 'm');
    await user.click(await screen.findByRole('button', { name: /bmoore@acme.com/ }));
    await user.click(screen.getByRole('button', { name: 'Yes, merge' }));
    expect(await screen.findByText('They are already one person.')).toBeInTheDocument();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('lists the hand decisions about the person and takes one back, then asks again', async () => {
    api.decisions
      .mockResolvedValueOnce({ items: [{ address_a: 'adam@tecovas.com', address_b: 'adam@tecovas.onmicrosoft.com', kind: 'separate', created_at: '2026-11-04T00:00:00Z' }] })
      .mockResolvedValue({ items: [] });
    const onChanged = vi.fn();
    render(<MergePanel person={person} onChanged={onChanged} />);
    expect(await screen.findByText(/Kept apart by you: adam@tecovas.com and adam@tecovas.onmicrosoft.com/)).toBeInTheDocument();
    expect(api.decisions).toHaveBeenCalledWith('c1', 'adam@tecovas.com');
    await userEvent.setup().click(screen.getByRole('button', { name: 'Take back: adam@tecovas.com and adam@tecovas.onmicrosoft.com' }));
    await waitFor(() => expect(api.removeDecision).toHaveBeenCalledWith('c1', 'adam@tecovas.com', 'adam@tecovas.onmicrosoft.com'));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByTestId('merge-decisions')).toBeNull());
  });

  it('shows no decisions section when there are none, or when the list cannot be read', async () => {
    api.decisions.mockRejectedValue(new Error('nope'));
    render(<MergePanel person={person} onChanged={vi.fn()} />);
    await waitFor(() => expect(api.decisions).toHaveBeenCalled());
    expect(screen.queryByTestId('merge-decisions')).toBeNull();
  });
});
