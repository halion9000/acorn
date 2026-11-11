import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ earlierOutcomes: vi.fn() }));
vi.mock('@/lib/api', async (original) => ({ ...(await original<typeof import('@/lib/api')>()), alertsApi: { earlierOutcomes: api.earlierOutcomes } }));

import { EarlierOutcomes, outcomesText } from './EarlierOutcomes';

const show = () => render(<SWRConfig value={{ provider: () => new Map() }}><EarlierOutcomes alertId="a1" /></SWRConfig>);

beforeEach(() => {
  api.earlierOutcomes.mockReset();
});

describe('outcomesText', () => {
  it('says too few under the minimum and never reads a pattern into it', () => {
    expect(outcomesText({ total: 2, enough: false, window_days: 180 })).toBe('Only 2 earlier alerts of this kind for this client in the last 180 days: too few to say what usually happens.');
    expect(outcomesText({ total: 1, enough: false, window_days: 180 })).toContain('Only 1 earlier alert of');
  });
  it('gives the counts, the tickets and the median time', () => {
    const t = outcomesText({ total: 5, enough: true, window_days: 180, by_status: { resolved: 3, fp: 1, new: 1 }, with_ticket: 2, median_hours_to_finish: 2.5, timed: 4, still_open: 1, by_disposition: {} });
    expect(t).toBe('5 earlier alerts of this kind for this client in the last 180 days: 3 resolved, 1 fp, 1 new. 2 had a ticket. Median time to finish 2.5 hours (from 4).');
  });
});

describe('EarlierOutcomes', () => {
  it('shows the card with how earlier alerts were judged', async () => {
    api.earlierOutcomes.mockResolvedValue({ total: 4, enough: true, window_days: 180, by_status: { resolved: 4 }, with_ticket: 0, median_hours_to_finish: 1, timed: 4, still_open: 0, by_disposition: { false_positive: 3, benign: 1 } });
    show();
    const card = await screen.findByTestId('earlier-outcomes');
    expect(card).toHaveTextContent('4 earlier alerts of this kind');
    expect(card).toHaveTextContent('How they were judged: 3 false positive, 1 benign.');
  });
  it('shows nothing when there are no earlier alerts', async () => {
    api.earlierOutcomes.mockResolvedValue({ total: 0, enough: false, window_days: 180 });
    show();
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId('earlier-outcomes')).toBeNull();
  });
});
