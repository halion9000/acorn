import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ notes: vi.fn(), addNote: vi.fn(), toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/lib/api', async (original) => ({ ...(await original<typeof import('@/lib/api')>()), alertsApi: { notes: api.notes, addNote: api.addNote } }));
vi.mock('react-hot-toast', () => ({ default: api.toast }));

import { AlertNotes } from './AlertNotes';

const show = () => render(<SWRConfig value={{ provider: () => new Map() }}><AlertNotes alertId="a1" /></SWRConfig>);

beforeEach(() => {
  for (const f of [api.notes, api.addNote, api.toast.success, api.toast.error]) f.mockReset();
});

describe('AlertNotes', () => {
  it('lists the notes with author and time, and says so when there are none', async () => {
    api.notes.mockResolvedValue([{ id: 'n1', author: 'hal@example.com', body: 'Called the user.\nNo answer.', created_at: '2026-11-08T10:15:00Z' }]);
    const { unmount } = show();
    const note = await screen.findByTestId('alert-note');
    expect(note).toHaveTextContent('hal@example.com · 2026-11-08 10:15 UTC');
    expect(note).toHaveTextContent('Called the user.');
    unmount();
    api.notes.mockResolvedValue([]);
    show();
    expect(await screen.findByTestId('alert-notes-empty')).toBeInTheDocument();
  });

  it('sends the trimmed text, clears the box and reloads; the button is off while the box is empty', async () => {
    api.notes.mockResolvedValue([]);
    api.addNote.mockResolvedValue({});
    const user = userEvent.setup();
    show();
    await screen.findByTestId('alert-notes-empty');
    const button = screen.getByRole('button', { name: 'Add note' });
    expect(button).toBeDisabled();
    await user.type(screen.getByLabelText('Add a note'), '  Spoke to IT.  ');
    await user.click(button);
    await waitFor(() => expect(api.addNote).toHaveBeenCalledWith('a1', 'Spoke to IT.'));
    await waitFor(() => expect(screen.getByLabelText('Add a note')).toHaveValue(''));
    expect(api.notes).toHaveBeenCalledTimes(2);
  });

  it('shows nothing when the notes cannot be loaded', async () => {
    api.notes.mockImplementation(() => Promise.reject(new Error('no')));
    show();
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryByTestId('alert-notes')).toBeNull();
  });
});
