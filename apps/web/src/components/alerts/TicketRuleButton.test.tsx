import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ make: vi.fn(), toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/lib/api', () => ({ ticketRulesApi: { make: api.make } }));
vi.mock('react-hot-toast', () => ({ default: api.toast }));

import { TicketRuleButton } from './TicketRuleButton';

beforeEach(() => {
  api.make.mockReset();
  api.toast.success.mockReset();
  api.toast.error.mockReset();
});

describe('TicketRuleButton', () => {
  it('asks first and makes nothing until the rule is confirmed, for the client by default', async () => {
    api.make.mockResolvedValue({ id: 'r1', queued_now: 1 });
    const user = userEvent.setup();
    render(<TicketRuleButton alertId="a1" clientName="Pirkey Barber PLLC" />);
    await user.click(screen.getByRole('button', { name: 'Auto-ticket' }));
    expect(api.make).not.toHaveBeenCalled();
    expect(screen.getByLabelText('for Pirkey Barber PLLC only')).toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Make the rule' }));
    await waitFor(() => expect(api.make).toHaveBeenCalledWith('a1', 'client', true));
    expect(await screen.findByRole('button', { name: 'Auto-ticket: on' })).toBeInTheDocument();
    expect(api.toast.success).toHaveBeenCalledWith('Rule made. A ticket for this alert is being opened.');
  });

  it('can be made for every client, and cancelled without making anything', async () => {
    api.make.mockResolvedValue({ id: 'r1', queued_now: 0 });
    const user = userEvent.setup();
    render(<TicketRuleButton alertId="a1" />);
    await user.click(screen.getByRole('button', { name: 'Auto-ticket' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(api.make).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Auto-ticket' }));
    expect(screen.getByLabelText('for this client only')).toBeChecked();
    await user.click(screen.getByLabelText('for every client'));
    await user.click(screen.getByRole('button', { name: 'Make the rule' }));
    await waitFor(() => expect(api.make).toHaveBeenCalledWith('a1', 'all', true));
    expect(api.toast.success).toHaveBeenCalledWith('Rule made. New alerts of this type will get a ticket.');
  });

  it('says what was refused (a duplicate rule, say) and stays open to try again', async () => {
    api.make.mockRejectedValueOnce(new Error('There is already a ticket rule for this type of alert here.'));
    const user = userEvent.setup();
    render(<TicketRuleButton alertId="a1" />);
    await user.click(screen.getByRole('button', { name: 'Auto-ticket' }));
    await user.click(screen.getByRole('button', { name: 'Make the rule' }));
    await waitFor(() => expect(api.toast.error).toHaveBeenCalledWith('There is already a ticket rule for this type of alert here.'));
    expect(screen.getByTestId('ticket-rule-form')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Auto-ticket: on' })).toBeNull();
  });
});

describe('the catch-up choice', () => {
  it('is on by default, can be turned off, and is what is sent; the message counts the tickets', async () => {
    api.make.mockResolvedValue({ id: 'r1', queued_now: 7 });
    const user = userEvent.setup();
    const a = render(<TicketRuleButton alertId="a1" />);
    await user.click(screen.getByRole('button', { name: 'Auto-ticket' }));
    expect(screen.getByLabelText(/Also open tickets and cases, once, for the alerts of this type that are already open/)).toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Make the rule' }));
    await waitFor(() => expect(api.make).toHaveBeenCalledWith('a1', 'client', true));
    expect(api.toast.success).toHaveBeenCalledWith('Rule made. 7 tickets are being opened (this alert and the others of its type that were open).');
    a.unmount();
    api.make.mockClear();
    render(<TicketRuleButton alertId="a2" />);
    await user.click(screen.getByRole('button', { name: 'Auto-ticket' }));
    await user.click(screen.getByLabelText(/Also open tickets and cases, once/));
    await user.click(screen.getByRole('button', { name: 'Make the rule' }));
    await waitFor(() => expect(api.make).toHaveBeenCalledWith('a2', 'client', false));
  });
});
