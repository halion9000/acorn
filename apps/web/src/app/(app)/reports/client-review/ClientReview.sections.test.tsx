import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));
vi.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams('client=c1') }));

import { ClientReview, type Review } from './ClientReview';

const reply = (body: unknown) => ({ ok: true, status: 200, json: () => Promise.resolve(body) });

const review: Review = {
  client_id: 'c1',
  client_name: 'Acme Dental',
  generated_at: '2026-10-28T12:00:00Z',
  window_days: 30,
  devices: { endpoints: 0, coverage: [], stale_agents: 0, offline: 0, with_known_exploited: null, with_ransomware_exploit: null },
  mfa: null,
  secure_score: null,
  alerts: { open: 0, critical_open: 0, high_open: 0, opened_30d: 0, closed_30d: 0 },
  cases: { open: 0, opened_30d: 0, resolved_30d: 0 },
  readiness: {
    met: 1,
    partly: 0,
    not_met: 0,
    unknown: 1,
    items: [
      { key: 'edr', question: 'Is endpoint detection on every computer?', status: 'met', evidence: '20 of 20 report Huntress.' },
      { key: 'backups', question: 'Are backups tested?', status: 'unknown', evidence: 'Not collected.' },
    ],
  },
  m365: [
    { group: 'Entra', question: 'Block legacy authentication', status: 'needs_person', evidence: '', license: 'Needs Microsoft Entra ID P1.' },
    { group: 'Entra', question: 'Admins have Multi-Factor', status: 'met', evidence: 'Every administrator has Multi-Factor.' },
    { group: 'Entra', question: 'Typed by someone', status: 'met', evidence: '', manual: true },
  ],
};

beforeEach(() => {
  window.localStorage.clear();
  authFetch.mockReset();
  authFetch.mockImplementation((url?: string) => Promise.resolve(String(url).startsWith('/api/v1/client-review/') ? reply(review) : reply([{ id: 'c1', name: 'Acme Dental' }])));
});

describe('the review sections', () => {
  it('says how many questions are open in each section and overall', async () => {
    render(<ClientReview />);
    expect(await screen.findByTestId('open-summary')).toHaveTextContent('Questions still open: 1 in readiness, 0 in technology, 1 in Microsoft 365, 0 in the assessment.');
    expect(screen.getByTestId('open-readiness')).toHaveTextContent('1 of 2 open');
    expect(screen.getByTestId('open-m365')).toHaveTextContent('1 of 3 open');
  });

  it('tags the answers A.C.O.R.N worked out, and not the open or typed ones', async () => {
    render(<ClientReview />);
    const readiness = await screen.findByTestId('readiness');
    expect(within(readiness).getAllByTestId('auto-answered')).toHaveLength(1);
    const m365 = screen.getByTestId('m365');
    expect(within(m365).getAllByTestId('auto-answered')).toHaveLength(1);
  });

  it('shows the licence a question needs, only on the questions that have one', async () => {
    render(<ClientReview />);
    const m365 = await screen.findByTestId('m365');
    const notes = within(m365).getAllByTestId('licence-note');
    expect(notes).toHaveLength(1);
    expect(notes[0]).toHaveTextContent('Needs Microsoft Entra ID P1.');
  });

  it('folds a section away, remembers it for next time, and shows it again', async () => {
    const user = userEvent.setup();
    const first = render(<ClientReview />);
    await screen.findByTestId('m365');
    const hide = screen.getByRole('button', { name: 'Hide Microsoft 365: suggested answers' });
    expect(hide).toHaveAttribute('aria-expanded', 'true');
    await user.click(hide);
    expect(screen.getByRole('button', { name: 'Show Microsoft 365: suggested answers' })).toHaveAttribute('aria-expanded', 'false');
    expect(JSON.parse(window.localStorage.getItem('client-review-folded') ?? '[]')).toEqual(['m365']);
    expect(screen.getByTestId('m365').closest('div')).toHaveClass('hidden');
    first.unmount();

    render(<ClientReview />);
    await screen.findByTestId('m365');
    expect(await screen.findByRole('button', { name: 'Show Microsoft 365: suggested answers' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Show Microsoft 365: suggested answers' }));
    expect(screen.getByTestId('m365').closest('div')).not.toHaveClass('hidden');
    expect(JSON.parse(window.localStorage.getItem('client-review-folded') ?? '[]')).toEqual([]);
  });

  it('downloads the review as a CSV named for the client and the day', async () => {
    const created: Blob[] = [];
    const clicked: string[] = [];
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: (b: Blob) => (created.push(b), 'blob:x'), revokeObjectURL: () => undefined }));
    const realCreate = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation(((tag: string) => {
      const el = realCreate(tag);
      if (tag === 'a') el.click = () => void clicked.push((el as HTMLAnchorElement).download);
      return el;
    }) as typeof document.createElement);
    const user = userEvent.setup();
    render(<ClientReview />);
    await screen.findByTestId('readiness');
    await user.click(screen.getByRole('button', { name: 'Download CSV' }));
    expect(clicked).toEqual(['client-review-acme-dental-2026-10-28.csv']);
    expect(created).toHaveLength(1);
    const text = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.readAsText(created[0]);
    });
    expect(text.split('\r\n')[0]).toBe('Section,Group,Question,Status,Answered by,Evidence,Note,Licence');
    expect(text).toContain('Block legacy authentication,needs_person,not answered,,,Needs Microsoft Entra ID P1.');
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });
});
