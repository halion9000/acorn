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
    await user.click(screen.getByTestId('ticket-rule-open'));
    expect(api.make).not.toHaveBeenCalled();
    expect(screen.getByLabelText('for Pirkey Barber PLLC only')).toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Make the rule' }));
    await waitFor(() => expect(api.make).toHaveBeenCalledWith('a1', 'client'));
    expect(await screen.findByTestId('ticket-rule-made')).toBeInTheDocument();
    expect(api.toast.success).toHaveBeenCalledWith('Rule made. A ticket for this alert is being opened.');
  });

  it('can be made for every client, and cancelled without making anything', async () => {
    api.make.mockResolvedValue({ id: 'r1', queued_now: 0 });
    const user = userEvent.setup();
    render(<TicketRuleButton alertId="a1" />);
    await user.click(screen.getByTestId('ticket-rule-open'));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(api.make).not.toHaveBeenCalled();
    await user.click(screen.getByTestId('ticket-rule-open'));
    expect(screen.getByLabelText('for this client only')).toBeChecked();
    await user.click(screen.getByLabelText('for every client'));
    await user.click(screen.getByRole('button', { name: 'Make the rule' }));
    await waitFor(() => expect(api.make).toHaveBeenCalledWith('a1', 'all'));
    expect(api.toast.success).toHaveBeenCalledWith('Rule made. New alerts of this type will get a ticket.');
  });

  it('says what was refused (a duplicate rule, say) and stays open to try again', async () => {
    api.make.mockRejectedValueOnce(new Error('There is already a ticket rule for this type of alert here.'));
    const user = userEvent.setup();
    render(<TicketRuleButton alertId="a1" />);
    await user.click(screen.getByTestId('ticket-rule-open'));
    await user.click(screen.getByRole('button', { name: 'Make the rule' }));
    await waitFor(() => expect(api.toast.error).toHaveBeenCalledWith('There is already a ticket rule for this type of alert here.'));
    expect(screen.getByTestId('ticket-rule-form')).toBeInTheDocument();
    expect(screen.queryByTestId('ticket-rule-made')).toBeNull();
  });
});
