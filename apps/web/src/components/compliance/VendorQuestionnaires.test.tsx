import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ questionnaires: vi.fn(), sendQuestionnaire: vi.fn(), cancelQuestionnaire: vi.fn() }));
vi.mock('@/lib/api', async (orig) => ({ ...(await orig<typeof import('@/lib/api')>()), vendorApi: api }));

import { VendorQuestionnaires, questionnaireLine } from './VendorQuestionnaires';

const open = { id: 'q1', created_at: '2026-11-21T10:00:00Z', expires_on: '2026-12-21', state: 'open', respondent_name: null, respondent_email: null, answered_at: null, answers: [], path: null, url: null, emailed: false };
const answered = {
  ...open,
  id: 'q2',
  state: 'answered',
  respondent_name: 'Vera Vendor',
  respondent_email: 'vera@v.test',
  answered_at: '2026-11-25T09:00:00Z',
  answers: [{ question: 'Do you require MFA?', answer: 'no', details: 'rolling out in Q1' }],
};

describe('A vendor security questionnaire', () => {
  beforeEach(() => {
    api.questionnaires.mockReset().mockResolvedValue([open, answered]);
    api.sendQuestionnaire.mockReset().mockResolvedValue({ ...open, id: 'q3', path: '/api/v1/public/vendor-questionnaire/TOK' });
    api.cancelQuestionnaire.mockReset().mockResolvedValue(undefined);
  });

  it('words each line by state', () => {
    expect(questionnaireLine(open as never)).toBe('open until 2026-12-21');
    expect(questionnaireLine(answered as never)).toBe('answered 2026-11-25 by Vera Vendor (vera@v.test)');
    expect(questionnaireLine({ ...open, state: 'expired' } as never)).toBe('expired 2026-12-21');
  });

  it('lists the answers, makes a link shown once and cancels an open one', async () => {
    const user = userEvent.setup();
    render(<VendorQuestionnaires clientId="" vendorId="v1" archived={false} contactEmail="am@v.test" />);
    expect(await screen.findByLabelText('Questionnaires sent')).toHaveTextContent('answered 2026-11-25 by Vera Vendor');
    expect(screen.getByText(/Do you require MFA\?/)).toHaveTextContent('No');
    await user.click(screen.getByRole('button', { name: 'Make a questionnaire link' }));
    expect(await screen.findByLabelText('New link')).toHaveTextContent('/api/v1/public/vendor-questionnaire/TOK');
    expect(api.sendQuestionnaire).toHaveBeenCalledWith('', 'v1', { send: false });
    await user.click(screen.getByRole('button', { name: 'Cancel this questionnaire link' }));
    await waitFor(() => expect(api.cancelQuestionnaire).toHaveBeenCalledWith('', 'v1', 'q1'));
  });

  it('asks for the e-mail option only when there is an address, and says why a link was refused', async () => {
    const user = userEvent.setup();
    api.sendQuestionnaire.mockRejectedValue(Object.assign(new Error('x'), { detail: 'E-mailing links needs PUBLIC_PAGES_BASE_URL' }));
    render(<VendorQuestionnaires clientId="" vendorId="v1" archived={false} contactEmail={null} />);
    expect(screen.getByRole('checkbox')).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Make a questionnaire link' }));
    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });

  it('offers no new link for an archived vendor', async () => {
    render(<VendorQuestionnaires clientId="" vendorId="v1" archived contactEmail={null} />);
    await screen.findByLabelText('Questionnaires sent');
    expect(screen.queryByRole('button', { name: 'Make a questionnaire link' })).toBeNull();
  });
});
