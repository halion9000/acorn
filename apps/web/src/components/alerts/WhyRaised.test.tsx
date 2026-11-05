import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ why: vi.fn() }));
vi.mock('@/lib/api', () => ({ alertsApi: { why: api.why } }));

import { WhyRaised } from './WhyRaised';

const show = () =>
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
      <WhyRaised alertId="a1" />
    </SWRConfig>,
  );
const open = () => {
  const box = screen.getByTestId('why-raised') as HTMLDetailsElement;
  box.open = true;
  fireEvent(box, new Event('toggle'));
};

beforeEach(() => api.why.mockReset());

describe('WhyRaised', () => {
  it('reads nothing until it is opened, then lists each fact', async () => {
    api.why.mockResolvedValue({ facts: [{ label: 'Raised by', value: 'huntress' }, { label: 'Severity', value: 'high' }] });
    show();
    expect(api.why).not.toHaveBeenCalled();
    open();
    await waitFor(() => expect(api.why).toHaveBeenCalledWith('a1'));
    expect(await screen.findByText('huntress')).toBeInTheDocument();
    expect(screen.getByText('Raised by')).toBeInTheDocument();
  });
  it('says so when there are no facts', async () => {
    api.why.mockResolvedValue({ facts: [] });
    show();
    open();
    expect(await screen.findByText(/records nothing about why/)).toBeInTheDocument();
  });
  it('says so when the read fails', async () => {
    api.why.mockRejectedValueOnce(new Error('boom'));
    show();
    open();
    expect(await screen.findByText('Could not load the reasons.')).toBeInTheDocument();
  });
});
