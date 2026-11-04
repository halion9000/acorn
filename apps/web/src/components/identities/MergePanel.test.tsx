import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ list: vi.fn(), mergePeople: vi.fn(), separatePeople: vi.fn() }));
vi.mock('@/lib/api', () => ({ identitiesApi: { list: api.list, mergePeople: api.mergePeople, separatePeople: api.separatePeople } }));

import { MergePanel } from './MergePanel';

const person = { client_id: 'c1', email: 'adam@tecovas.com', display_name: 'Adam', aliases: [{ email: 'adam@tecovas.onmicrosoft.com', reason: "the same name on the client's Microsoft address" }] };
const other = { key: 'c1:bmoore@acme.com', email: 'bmoore@acme.com', display_name: 'Brandon Moore', tools: ['cipp', 'huntress'] };

beforeEach(() => {
  api.list.mockReset().mockResolvedValue({ items: [other, { ...other, key: 'self', email: person.email }] });
  api.mergePeople.mockReset().mockResolvedValue({ kind: 'merge' });
  api.separatePeople.mockReset().mockResolvedValue({ kind: 'separate' });
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
});
