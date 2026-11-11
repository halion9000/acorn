import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ getResponseTimes: vi.fn() }));
vi.mock('@/lib/api', () => ({ insightsApi: { getResponseTimes: api.getResponseTimes } }));

import { ClientResponseTable, hoursLabel, loadResponseTimes } from './ClientResponseTable';

const show = (onPick = vi.fn()) => {
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <ClientResponseTable window="7d" onPick={onPick} />
    </SWRConfig>,
  );
  return onPick;
};

beforeEach(() => api.getResponseTimes.mockReset());

describe('hoursLabel', () => {
  it('reads in minutes under an hour, hours up to two days, then days', () => {
    expect(hoursLabel(0.5)).toBe('30 min');
    expect(hoursLabel(0.001)).toBe('1 min');
    expect(hoursLabel(3.46)).toBe('3.5 h');
    expect(hoursLabel(47)).toBe('47 h');
    expect(hoursLabel(60)).toBe('2.5 days');
    expect(hoursLabel(-1)).toBe('');
  });
});

describe('ClientResponseTable', () => {
  it('lists each client with its typical time and alert count, shows the slow end only where there are enough alerts, and picks a client on press', async () => {
    api.getResponseTimes.mockResolvedValue({
      window: '7d',
      clients: [
        { client_id: 'c1', client_name: 'Slow Co', median_hours: 60, p90_hours: 100, alerts: 8 },
        { client_id: 'c2', client_name: 'Quick Co', median_hours: 0.5, p90_hours: 0.7, alerts: 2 },
      ],
    });
    const onPick = show();
    const table = await screen.findByTestId('client-response-table');
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows[0]).toHaveTextContent('Slow Co');
    expect(rows[0]).toHaveTextContent('2.5 days');
    expect(rows[0]).toHaveTextContent('4.2 days');
    expect(rows[1]).toHaveTextContent('30 min');
    expect(rows[1]).toHaveTextContent('too few alerts');
    await userEvent.click(within(rows[0]).getByRole('button', { name: 'Slow Co' }));
    expect(onPick).toHaveBeenCalledWith('c1');
  });

  it('shows nothing when no client finished anything', async () => {
    api.getResponseTimes.mockResolvedValue({ window: '7d', clients: [] });
    const { container } = render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
        <ClientResponseTable window="7d" onPick={() => undefined} />
      </SWRConfig>,
    );
    await waitFor(() => expect(api.getResponseTimes).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 20));
    expect(container.querySelector('[data-testid="client-response-table"]')).toBeNull();
  });

  it('loadResponseTimes gives the answer, or null when the server cannot answer (an older server has no such route)', async () => {
    api.getResponseTimes.mockResolvedValueOnce({ window: '7d', clients: [] });
    expect(await loadResponseTimes('7d')).toEqual({ window: '7d', clients: [] });
    api.getResponseTimes.mockImplementationOnce(() => {
      throw new Error('404');
    });
    expect(await loadResponseTimes('7d')).toBeNull();
  });
});
