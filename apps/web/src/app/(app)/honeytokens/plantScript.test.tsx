import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import HoneytokensPage from './page';
import { plantScript, safeFileName } from './tokens';

const authFetch = vi.fn();
vi.mock('@/lib/auth-session', () => ({ authFetch: (...a: unknown[]) => authFetch(...a) }));
vi.mock('swr', async () => {
  const React = await import('react');
  return {
    __esModule: true,
    mutate: vi.fn(),
    default: function useFakeSwr(key: string | null, fetcher: (k: string) => Promise<unknown>) {
      const [data, setData] = React.useState<unknown>(undefined);
      React.useEffect(() => {
        if (key === null) return;
        let live = true;
        void fetcher(key).then((d) => live && setData(d));
        return () => {
          live = false;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
      }, [key]);
      return { data, isLoading: data === undefined };
    },
  };
});

const reply = (body: unknown) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body), text: () => Promise.resolve(JSON.stringify(body)) });
const LINK = 'https://acorn.example.com/api/v1/canary/11111111-1111-4111-8111-111111111111';
const link = { id: '1', name: 'Finance wiki bait', description: null, token_type: 'url', token_value: 'x', metadata: { token_data: { url: LINK }, detection: 'link' }, status: 'active', expires_at: null, created_at: '2026-10-18T00:00:00Z', created_by: null };
const aws = { ...link, id: '2', name: 'Fake AWS', token_type: 'aws_key', metadata: { token_data: { access_key_id: 'AKIAXXXXXXXXXXXXXXXX' }, detection: 'none' } };

beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockImplementation((url: string) => (url.includes('/triggers') ? reply([]) : reply([link, aws])));
});
afterEach(() => cleanup());

describe('plantScript', () => {
  it('makes a shortcut file that opens the token link, named after the token', () => {
    const s = plantScript(link as never)!;
    expect(s).toContain("$file = 'Finance wiki bait.url'");
    expect(s).toContain(`'URL=${LINK}'`);
    expect(s).toContain('[InternetShortcut]');
  });

  it('gives nothing for a decoy that cannot alert, or a link that is not a plain web address', () => {
    expect(plantScript(aws as never)).toBeNull();
    for (const bad of ["https://x.test/a'; calc; '", 'javascript:alert(1)', 'https://x.test/a b', 'https://x.test/$(whoami)']) {
      expect(plantScript({ ...link, metadata: { token_data: { url: bad }, detection: 'link' } } as never), bad).toBeNull();
    }
  });

  it('keeps a quote, a path or a command out of the file name', () => {
    expect(safeFileName("..\\..\\x'; calc; $(y)")).toBe('x calc y');
    expect(safeFileName('')).toBe('Document');
    expect(plantScript({ ...link, name: "a'b" } as never)).toContain("$file = 'ab.url'");
  });
});

describe('the plant script on the page', () => {
  it('shows the script and a copy button for a link token', async () => {
    render(<HoneytokensPage />);
    await userEvent.setup().click(await screen.findByText('Finance wiki bait'));
    const box = await screen.findByTestId('plant-script');
    expect(box.textContent).toContain(`URL=${LINK}`);
    expect(box.querySelector('button')).not.toBeNull();
  });

  it('shows none for a decoy-only token', async () => {
    render(<HoneytokensPage />);
    await userEvent.setup().click(await screen.findByText('Fake AWS'));
    await screen.findByTestId('detection');
    expect(screen.queryByTestId('plant-script')).toBeNull();
  });
});
