import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const authFetch = vi.fn();
vi.mock('@/lib/auth-session', () => ({ authFetch: (...a: unknown[]) => authFetch(...a) }));

import { RetentionPreview } from './RetentionPreview';

const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }));

beforeEach(() => authFetch.mockReset());

describe('RetentionPreview', () => {
  it('lists what would be deleted by kind with the note, and what could not be counted', async () => {
    authFetch.mockImplementation(() => json({ would_delete: { response_actions: 12345, alerts: 0 }, failed: { posture_history: 'OperationalError' }, switched_on: true, note: 'A dry run: nothing was deleted.' }));
    render(<RetentionPreview />);
    expect(await screen.findByTestId('retention-response_actions')).toHaveTextContent('Finished response actions12,345');
    expect(screen.getByTestId('retention-alerts')).toHaveTextContent('0');
    expect(screen.getByTestId('retention-preview')).toHaveTextContent('A dry run: nothing was deleted.');
    expect(screen.getByTestId('retention-failed')).toHaveTextContent('Posture history');
    expect(authFetch).toHaveBeenCalledWith('/api/v1/data-lifecycle/retention/preview');
  });
  it('says nothing is due when the list is empty', async () => {
    authFetch.mockImplementation(() => json({ would_delete: {}, failed: {}, switched_on: false, note: 'n' }));
    render(<RetentionPreview />);
    expect(await screen.findByTestId('retention-none')).toBeInTheDocument();
  });
  it('shows nothing for someone who may not ask, or an answer of another shape', async () => {
    authFetch.mockImplementation(() => json({ detail: 'forbidden' }, 403));
    const { unmount } = render(<RetentionPreview />);
    await waitFor(() => expect(authFetch).toHaveBeenCalled());
    expect(screen.queryByTestId('retention-preview')).toBeNull();
    unmount();
    authFetch.mockImplementation(() => json({ services: [] }));
    render(<RetentionPreview />);
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId('retention-preview')).toBeNull();
  });
});
