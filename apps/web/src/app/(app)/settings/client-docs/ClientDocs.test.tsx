import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ClientDocs, agoWords, summaryLine, type DocSummary } from './ClientDocs';

const authFetch = vi.fn();
vi.mock('@/lib/auth-session', () => ({ authFetch: (...a: unknown[]) => authFetch(...a) }));

const json = (data: unknown, status = 200) => ({ ok: status < 400, status, json: () => Promise.resolve(data) });
const SUMMARY: DocSummary[] = [
  { client_id: 'c-2', client: 'Tecovas, Inc.', kinds: { document: 3, password: 2 }, refreshed_at: '2026-10-28T10:00:00Z' },
  { client_id: 'c-1', client: 'Airport Security Park', kinds: { configuration: 4 }, refreshed_at: '2026-10-28T11:00:00Z' },
];

function route(handlers: Record<string, (url: string) => unknown>) {
  authFetch.mockImplementation(async (url: string) => {
    const key = Object.keys(handlers).find((k) => url.startsWith(k));
    return key ? handlers[key](url) : json({}, 404);
  });
}

beforeEach(() => {
  authFetch.mockReset();
});
afterEach(() => cleanup());

describe('summaryLine / agoWords', () => {
  const NOW = Date.parse('2026-10-28T12:00:00Z');
  it('counts the records and clients and says when the newest was refreshed', () => {
    expect(summaryLine(SUMMARY, NOW)).toBe('9 records for 2 clients; the newest was refreshed 60 minutes ago.');
    expect(summaryLine([SUMMARY[0]], NOW)).toContain('1 client;');
  });
  it('says never for no date', () => {
    expect(agoWords(null)).toBe('never');
    expect(agoWords('2026-10-28T11:59:30Z', NOW)).toBe('just now');
    expect(agoWords('2026-10-26T12:00:00Z', NOW)).toBe('2 days ago');
  });
});

describe('ClientDocs, when things go wrong', () => {
  it('a summary that could not be read says so, not that nothing has been read from IT Glue', async () => {
    route({ '/api/v1/client-documents/summary': () => json({}, 500) });
    render(<ClientDocs />);
    expect(await screen.findByTestId('summary-error')).toHaveTextContent('Could not read what has been synced from IT Glue: The API answered 500');
    expect(screen.queryByTestId('docs-summary')).toBeNull();
  });

  it('a refused summary says the person has no access', async () => {
    route({ '/api/v1/client-documents/summary': () => json({}, 403) });
    render(<ClientDocs />);
    expect(await screen.findByTestId('summary-error')).toHaveTextContent("You do not have access to the clients' documentation.");
  });

  it('a network failure on the summary is shown with its message', async () => {
    authFetch.mockRejectedValue(new Error('network down'));
    render(<ClientDocs />);
    expect(await screen.findByTestId('summary-error')).toHaveTextContent('network down');
  });

  it('a slower answer to an older search does not replace the newer one', async () => {
    let releaseSlow: (v: unknown) => void = () => undefined;
    const slow = new Promise((resolve) => {
      releaseSlow = resolve;
    });
    const hit = (title: string) => [{ client_id: 'c-1', client: 'Airport Security Park', kind: 'document', title, folder: null, url: null, snippet: 's' }];
    authFetch.mockImplementation(async (url: string) => {
      if (url.startsWith('/api/v1/client-documents/summary')) return json(SUMMARY);
      if (url.includes('q=first')) return slow;
      return json(hit('The newer answer'));
    });
    render(<ClientDocs />);
    await screen.findByTestId('docs-summary');
    const box = screen.getByLabelText('Search the documentation');
    fireEvent.change(box, { target: { value: 'first search' } });
    fireEvent.click(screen.getByRole('button', { name: /Search/ }));
    fireEvent.change(box, { target: { value: 'second search' } });
    fireEvent.submit(box.closest('form') as HTMLFormElement);
    expect(await screen.findByText('The newer answer')).toBeInTheDocument();
    releaseSlow(json(hit('The older answer')));
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText('The older answer')).toBeNull();
    expect(screen.getByText('The newer answer')).toBeInTheDocument();
    expect(screen.getByTestId('docs-results')).toHaveTextContent('second search');
  });
});

describe('ClientDocs', () => {
  it('says nothing has been read yet when there is no documentation, and offers no client picker', async () => {
    route({ '/api/v1/client-documents/summary': () => json([]) });
    render(<ClientDocs />);
    expect(await screen.findByTestId('docs-summary')).toHaveTextContent('Nothing has been read from IT Glue yet');
    expect(screen.queryByRole('combobox', { name: 'Client' })).toBeNull();
  });

  it('searches, shows each match with its kind, client, folder, snippet and link, and marks a password entry as masked', async () => {
    route({
      '/api/v1/client-documents/summary': () => json(SUMMARY),
      '/api/v1/client-documents?': () =>
        json([
          { client_id: 'c-2', client: 'Tecovas, Inc.', kind: 'password', title: 'Microsoft 365 admin', folder: 'Microsoft', url: 'https://liveoak.itglue.com/1/passwords/2', snippet: 'Username: admin@tecovas.com' },
          { client_id: 'c-2', client: 'Tecovas, Inc.', kind: 'document', title: 'Onboarding guide', folder: 'HR', url: 'javascript:alert(1)', snippet: 'Create the account in Entra.' },
        ]),
    });
    render(<ClientDocs />);
    await screen.findByTestId('docs-summary');
    fireEvent.change(screen.getByLabelText('Search the documentation'), { target: { value: 'microsoft admin' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    const results = await screen.findByTestId('docs-results');
    expect(results).toHaveTextContent('2 best matches for “microsoft admin”');
    expect(screen.getByRole('link', { name: 'Microsoft 365 admin' })).toHaveAttribute('href', 'https://liveoak.itglue.com/1/passwords/2');
    expect(results).toHaveTextContent('Password entry');
    expect(results).toHaveTextContent('The password is masked in IT Glue');
    expect(results).toHaveTextContent('Tecovas, Inc. · Microsoft');
    expect(screen.queryByRole('link', { name: 'Onboarding guide' })).toBeNull();
    expect(results).toHaveTextContent('Onboarding guide');
  });

  it('labels a ticket as a ticket, linking to it in the ticketing tool', async () => {
    route({
      '/api/v1/client-documents/summary': () => json(SUMMARY),
      '/api/v1/client-documents?': () =>
        json([{ client_id: 'c-1', client: 'Airport Security Park', kind: 'ticket', title: '#1234 Wifi drops', folder: 'Closed', url: 'https://acme.halopsa.com/tickets?id=1234', snippet: 'Moved the AP to the hallway.' }]),
    });
    render(<ClientDocs />);
    await screen.findByTestId('docs-summary');
    fireEvent.change(screen.getByLabelText('Search the documentation'), { target: { value: 'wifi drops' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    const results = await screen.findByTestId('docs-results');
    expect(results).toHaveTextContent('Ticket');
    expect(results).toHaveTextContent('Airport Security Park · Closed');
    expect(screen.getByRole('link', { name: '#1234 Wifi drops' })).toHaveAttribute('href', 'https://acme.halopsa.com/tickets?id=1234');
  });

  it('asks for one client when one is picked, with the words and a limit', async () => {
    route({ '/api/v1/client-documents/summary': () => json(SUMMARY), '/api/v1/client-documents?': () => json([]) });
    render(<ClientDocs />);
    const picker = await screen.findByRole('combobox', { name: 'Client' });
    expect(Array.from((picker as HTMLSelectElement).options).map((o) => o.text)).toEqual(['All clients', 'Airport Security Park', 'Tecovas, Inc.']);
    fireEvent.change(picker, { target: { value: 'c-1' } });
    fireEvent.change(screen.getByLabelText('Search the documentation'), { target: { value: 'firewall' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    await waitFor(() => expect(authFetch.mock.calls.some((c) => String(c[0]) === '/api/v1/client-documents?q=firewall&limit=20&client_id=c-1')).toBe(true));
    expect(await screen.findByTestId('docs-results')).toHaveTextContent('Nothing in the documentation matches “firewall”');
  });

  it('does not search for less than two letters, and shows a refusal plainly', async () => {
    route({ '/api/v1/client-documents/summary': () => json(SUMMARY), '/api/v1/client-documents?': () => json({}, 403) });
    render(<ClientDocs />);
    await screen.findByTestId('docs-summary');
    fireEvent.change(screen.getByLabelText('Search the documentation'), { target: { value: 'a' } });
    expect(screen.getByRole('button', { name: 'Search' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Search the documentation'), { target: { value: 'vpn' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    expect(await screen.findByRole('alert')).toHaveTextContent("You do not have access to the clients' documentation");
  });
});
