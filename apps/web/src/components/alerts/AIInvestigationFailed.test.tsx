import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ investigate: vi.fn(), getInvestigation: vi.fn() }));
vi.mock('@/lib/api', async (importOriginal) => ({ ...(await importOriginal<typeof import('@/lib/api')>()), agentsApi: { investigate: api.investigate, getInvestigation: api.getInvestigation } }));

import { AIInvestigation } from './AlertDetailView';

beforeEach(() => {
  api.investigate.mockReset();
  api.getInvestigation.mockReset();
});

describe('a failed investigation', () => {
  it('says it failed and why, instead of only a red dot', async () => {
    api.investigate.mockResolvedValue({ id: 'r1', alertId: 'a1', status: 'running', startedAt: 't' });
    api.getInvestigation.mockResolvedValue({ id: 'r1', alertId: 'a1', status: 'failed', startedAt: 't', error: 'The investigation stopped with an error before it finished.' });
    render(<AIInvestigation alertId="a1" />);
    await userEvent.click(screen.getByRole('button', { name: 'Start AI Investigation' }));
    expect(await screen.findByTestId('investigation-error')).toHaveTextContent('The investigation stopped with an error before it finished.');
    expect(screen.getByText('failed')).toBeInTheDocument();
  });

  it('still says something when the server gave no reason, and shows nothing of the kind for a completed one', async () => {
    api.investigate.mockResolvedValue({ id: 'r2', alertId: 'a1', status: 'running', startedAt: 't' });
    api.getInvestigation.mockResolvedValue({ id: 'r2', alertId: 'a1', status: 'failed', startedAt: 't' });
    const a = render(<AIInvestigation alertId="a1" />);
    await userEvent.click(screen.getByRole('button', { name: 'Start AI Investigation' }));
    expect(await screen.findByTestId('investigation-error')).toHaveTextContent('The investigation failed.');
    a.unmount();
    api.investigate.mockResolvedValue({ id: 'r3', alertId: 'a1', status: 'running', startedAt: 't' });
    api.getInvestigation.mockResolvedValue({ id: 'r3', alertId: 'a1', status: 'completed', startedAt: 't', findings: 'All clear' });
    render(<AIInvestigation alertId="a1" />);
    await userEvent.click(screen.getByRole('button', { name: 'Start AI Investigation' }));
    await waitFor(() => expect(screen.getByText('completed')).toBeInTheDocument());
    expect(screen.queryByTestId('investigation-error')).toBeNull();
  });
});
