import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import HoneytokensPage from './page';
import { PLANT_SCRIPT } from './HowTo';
import { TOKEN_TYPES, TOKEN_TYPE_ORDER, canAlert, plantables } from './tokens';

const authFetch = vi.fn();
vi.mock('@/lib/auth-session', () => ({ authFetch: (...a: unknown[]) => authFetch(...a) }));
vi.mock('swr', async () => {
  const React = await import('react');
  const mutate = vi.fn();
  return {
    __esModule: true,
    mutate,
    default: function useFakeSwr(key: string | null, fetcher: (k: string) => Promise<unknown>) {
      const [data, setData] = React.useState<unknown>(undefined);
      const [isLoading, setLoading] = React.useState(true);
      React.useEffect(() => {
        if (key === null) return;
        let live = true;
        setLoading(true);
        void fetcher(key).then((d) => {
          if (live) {
            setData(d);
            setLoading(false);
          }
        });
        return () => {
          live = false;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
      }, [key]);
      return { data, isLoading };
    },
  };
});

const reply = (body: unknown, status = 200) => Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body), text: () => Promise.resolve(JSON.stringify(body)) });

const linkToken = {
  id: '11111111-1111-4111-8111-111111111111',
  name: 'Finance wiki bait',
  description: null,
  token_type: 'url',
  token_value: "{'url': 'x'}",
  metadata: { token_data: { url: 'http://localhost:3000/api/v1/canary/11111111-1111-4111-8111-111111111111' }, detection: 'link' },
  status: 'active',
  expires_at: null,
  created_at: '2026-10-18T00:00:00Z',
  created_by: null,
};
const awsToken = { ...linkToken, id: '22222222-2222-4222-8222-222222222222', name: 'Fake AWS', token_type: 'aws_key', metadata: { token_data: { access_key_id: 'AKIAXXXXXXXXXXXXXXXX', secret_access_key: 'abc' }, detection: 'none' } };

beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockImplementation((url: string) => {
    if (url.includes('/triggers')) return reply([]);
    return reply([linkToken, awsToken]);
  });
});
afterEach(() => cleanup());

describe('what the page says about detection', () => {
  it('only a link or a document with a link claims to alert; every other type says it is a decoy only', () => {
    const alerting = TOKEN_TYPE_ORDER.filter((t) => TOKEN_TYPES[t].alerts);
    expect(alerting).toEqual(['url', 'file']);
    for (const t of TOKEN_TYPE_ORDER.filter((x) => !TOKEN_TYPES[x].alerts)) expect(TOKEN_TYPES[t].label).toContain('decoy only');
  });

  it('judges a token by what the service stored, and an old token by its type', () => {
    expect(canAlert({ token_type: 'aws_key', metadata: { detection: 'link' } })).toBe(true);
    expect(canAlert({ token_type: 'url', metadata: { detection: 'none' } })).toBe(false);
    expect(canAlert({ token_type: 'url', metadata: {} })).toBe(true);
    expect(canAlert({ token_type: 'dns', metadata: {} })).toBe(false);
    expect(canAlert({ token_type: 'made-up', metadata: {} })).toBe(false);
  });

  it('lists the link first, then the other values, and skips empty ones', () => {
    const rows = plantables({ metadata: { token_data: { checksum: 'c', filename: 'f.zip', beacon_url: 'http://x/y', empty: '', other: 'o' } } });
    expect(rows.map(([k]) => k)).toEqual(['beacon_url', 'filename', 'checksum', 'other']);
  });
});

describe('the Honeytokens page', () => {
  it('shows in the list which tokens can alert and which are decoys only', async () => {
    render(<HoneytokensPage />);
    expect(await screen.findByText('Finance wiki bait')).toBeInTheDocument();
    expect(screen.getByText('Alerts when opened')).toBeInTheDocument();
    expect(screen.getByText('Decoy only')).toBeInTheDocument();
  });

  it('opens a token to show exactly what to plant, with the link to copy, and the way to test it', async () => {
    render(<HoneytokensPage />);
    await userEvent.setup().click(await screen.findByText('Finance wiki bait'));
    const detection = await screen.findByTestId('detection');
    expect(detection.textContent).toContain('alerts when its link is opened');
    expect(screen.getByText(/api\/v1\/canary\/11111111/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'open the link' })).toHaveAttribute('href', linkToken.metadata.token_data.url);
    expect(screen.getByText(/No triggers yet/)).toBeInTheDocument();
  });

  it('tells you a decoy-only token will not alert, and shows no test link for it', async () => {
    render(<HoneytokensPage />);
    await userEvent.setup().click(await screen.findByText('Fake AWS'));
    expect((await screen.findByTestId('detection')).textContent).toContain('decoy only');
    expect(screen.queryByRole('link', { name: 'open the link' })).toBeNull();
  });

  it('the create form says before you create whether the chosen type will alert', async () => {
    render(<HoneytokensPage />);
    await userEvent.setup().click(await screen.findByRole('button', { name: '+ New Token' }));
    expect(screen.getByTestId('type-help').textContent).toContain('Alerts when opened');
    await userEvent.setup().selectOptions(screen.getByLabelText('Token type'), 'aws_key');
    expect(screen.getByTestId('type-help').textContent).toContain('it will not alert');
  });

  it('after creating a token it opens straight to what to plant', async () => {
    const created = { ...linkToken, id: '33333333-3333-4333-8333-333333333333', name: 'Fresh', metadata: { token_data: { url: 'http://localhost:3000/api/v1/canary/33333333-3333-4333-8333-333333333333' }, detection: 'link' } };
    authFetch.mockImplementation((url: string, init?: RequestInit) => {
      if (init?.method === 'POST') return reply(created, 201);
      if (url.includes('/triggers')) return reply([]);
      return reply([linkToken, awsToken, created]);
    });
    render(<HoneytokensPage />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: '+ New Token' }));
    await user.type(screen.getByPlaceholderText(/Finance share passwords note/), 'Fresh');
    await user.click(screen.getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(screen.getByTestId('detection')).toBeInTheDocument());
    expect(screen.getByText(/api\/v1\/canary\/33333333/)).toBeInTheDocument();
  });
});


describe('the How to panel', () => {
  it('is closed until asked for, opens from the How to button and closes again', async () => {
    render(<HoneytokensPage />);
    await screen.findByText('Finance wiki bait');
    expect(screen.queryByTestId('howto')).toBeNull();
    const button = screen.getByRole('button', { name: 'How to' });
    expect(button).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(button);
    expect(screen.getByTestId('howto')).toBeInTheDocument();
    expect(button).toHaveAttribute('aria-expanded', 'true');
    await userEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.queryByTestId('howto')).toBeNull();
  });

  it('explains what alerts, the steps, the ways to plant it, where not to, and inside against outside', async () => {
    render(<HoneytokensPage />);
    await userEvent.click(await screen.findByRole('button', { name: 'How to' }));
    const panel = screen.getByTestId('howto');
    for (const heading of ['What it is', 'Steps', 'Ways to plant it', 'Where not to put it', 'Inside or outside your network']) {
      expect(within(panel).getByRole('heading', { name: heading })).toBeInTheDocument();
    }
    expect(panel).toHaveTextContent('Only the Link and Document with a link types can do this');
    expect(panel).toHaveTextContent('one token per place');
    expect(panel).toHaveTextContent('Plain text files never open links');
    expect(panel).toHaveTextContent('Inside, as it works today');
    expect(panel).toHaveTextContent('/api/v1/canary/*');
  });

  it('gives a script that makes a shortcut file opening the pasted link, and copies it exactly', async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: write }, configurable: true });
    render(<HoneytokensPage />);
    await userEvent.click(await screen.findByRole('button', { name: 'How to' }));
    const shown = screen.getByTestId('howto-script').textContent ?? '';
    expect(shown).toContain("$link = 'PASTE THE TOKEN LINK HERE'");
    expect(shown).toContain('[InternetShortcut]');
    expect(shown).toContain('URL=$link');
    expect(shown).toContain('.url');
    await userEvent.click(screen.getByRole('button', { name: 'Copy' }));
    expect(write).toHaveBeenCalledWith(PLANT_SCRIPT);
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument();
  });

  it('the script has no token, secret or address of its own in it', () => {
    expect(PLANT_SCRIPT).not.toMatch(/https?:\/\//);
    expect(PLANT_SCRIPT.split('\n')).toHaveLength(2);
  });
});
