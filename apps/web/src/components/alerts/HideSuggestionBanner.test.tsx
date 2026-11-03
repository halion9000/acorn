import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ hideSuggestion: vi.fn() }));
vi.mock('@/lib/api', () => ({ alertsApi: api }));

import { HideSuggestionBanner } from './HideSuggestionBanner';

const view = (status = 'false_positive', onHide = vi.fn()) => (
  <SWRConfig value={{ provider: () => new Map() }}>
    <HideSuggestionBanner alertId="a1" status={status} onHide={onHide} />
  </SWRConfig>
);

beforeEach(() => {
  api.hideSuggestion.mockReset();
});

describe('the hide suggestion', () => {
  it('offers to hide the type after repeated false positives, and the button opens the hide window', async () => {
    api.hideSuggestion.mockResolvedValue({ suggest: true, false_positives: 4, threshold: 3, days: 90 });
    const onHide = vi.fn();
    render(view('false_positive', onHide));
    const note = await screen.findByTestId('hide-suggestion');
    expect(note).toHaveTextContent('4 times in the last 90 days');
    await userEvent.click(screen.getByRole('button', { name: 'Hide alert type' }));
    expect(onHide).toHaveBeenCalledTimes(1);
  });

  it('says nothing when there is no suggestion', async () => {
    api.hideSuggestion.mockResolvedValue({ suggest: false, false_positives: 1, threshold: 3, days: 90 });
    render(view());
    await waitFor(() => expect(api.hideSuggestion).toHaveBeenCalled());
    expect(screen.queryByTestId('hide-suggestion')).toBeNull();
  });

  it('does not even ask unless the alert was closed as a false positive', () => {
    render(view('investigating'));
    expect(api.hideSuggestion).not.toHaveBeenCalled();
  });

  it('says nothing when the server cannot answer', async () => {
    api.hideSuggestion.mockRejectedValue(new Error('The server answered 404.'));
    render(view());
    await waitFor(() => expect(api.hideSuggestion).toHaveBeenCalled());
    expect(screen.queryByTestId('hide-suggestion')).toBeNull();
  });
});
