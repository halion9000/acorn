import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { QuestionHistory, entryText, type HistoryEntry } from './QuestionHistory';

const entry = (over: Partial<HistoryEntry> = {}): HistoryEntry => ({ at: '2026-10-29T12:00:00Z', source: 'automatic', status: 'partly', detail: '17 of 20 machines report Huntress.', note: null, actor: null, ...over });

beforeEach(() => authFetch.mockReset());
afterEach(() => cleanup());

describe('entryText', () => {
  it('says the status and the evidence, and who typed a typed one', () => {
    expect(entryText(entry())).toBe('Partly - 17 of 20 machines report Huntress.');
    expect(entryText(entry({ source: 'manual', status: 'met', detail: null, actor: 'tech@liveoak.test' }))).toBe('Met (by tech@liveoak.test)');
    expect(entryText(entry({ source: 'manual', status: null, detail: null }))).toBe('Note only');
  });
});

describe('QuestionHistory', () => {
  const view = () => render(<QuestionHistory clientId="c1" section="readiness" questionKey="edr" />);

  it('reads nothing until pressed, then lists the changes newest first, automatic and typed', async () => {
    authFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([entry({ source: 'manual', status: 'met', detail: null, note: 'Confirmed with the client', actor: 'tech@liveoak.test', at: '2026-10-30T09:00:00Z' }), entry()]),
    });
    view();
    expect(authFetch).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'History of: edr' }));
    const panel = await screen.findByTestId('question-history');
    expect(authFetch).toHaveBeenCalledWith('/api/v1/client-review/c1/history?section=readiness&key=edr');
    const items = panel.querySelectorAll('li');
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent('Typed');
    expect(items[0]).toHaveTextContent('Met (by tech@liveoak.test)');
    expect(items[0]).toHaveTextContent('Note: Confirmed with the client');
    expect(items[1]).toHaveTextContent('Automatic');
    expect(items[1]).toHaveTextContent('17 of 20 machines report Huntress.');
  });

  it('says so when nothing is recorded, and when the history cannot be read, and closes again', async () => {
    authFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve([]) });
    view();
    const button = screen.getByRole('button', { name: 'History of: edr' });
    await userEvent.click(button);
    expect(await screen.findByText(/Nothing recorded yet/)).toBeInTheDocument();
    await userEvent.click(button);
    expect(screen.queryByTestId('question-history')).toBeNull();
    authFetch.mockResolvedValueOnce({ ok: false, status: 500, json: () => Promise.resolve({}) });
    await userEvent.click(button);
    expect(await screen.findByRole('alert')).toHaveTextContent('The API answered 500');
  });
});
