import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const nav = vi.hoisted(() => ({ push: vi.fn(), pathname: '/alerts' }));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
const searchApi = vi.hoisted(() => ({ search: vi.fn() }));
vi.mock('@/lib/api', async (original) => ({ ...(await original<typeof import('@/lib/api')>()), searchApi }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: nav.push }), usePathname: () => nav.pathname }));
vi.mock('react-hot-toast', () => ({ __esModule: true, default: toast }));
vi.mock('framer-motion', async () => {
  const React = await import('react');
  const strip = ({ children, initial, animate, exit, transition, ...rest }: Record<string, unknown>) => React.createElement('div', rest as object, children as React.ReactNode);
  return { motion: { div: strip }, AnimatePresence: ({ children }: { children: React.ReactNode }) => React.createElement(React.Fragment, null, children) };
});

import { CommandPalette, hitHref } from './CommandPalette';

const KEY = 'aisoc.palette.recent';

beforeEach(() => {
  nav.push.mockReset();
  nav.pathname = '/alerts';
  toast.success.mockReset();
  toast.error.mockReset();
  searchApi.search.mockReset();
  searchApi.search.mockResolvedValue({ query: '', hits: [] });
  localStorage.clear();
  // cmdk measures and scrolls; jsdom has neither.
  (globalThis as Record<string, unknown>).ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} };
  Element.prototype.scrollIntoView ??= () => {};
});

const openIt = () => {
  render(<CommandPalette />);
  fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
};

describe('CommandPalette', () => {
  it('is closed until Ctrl+K or Cmd+K, which also closes it again', () => {
    render(<CommandPalette />);
    expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    expect(screen.getByRole('dialog', { name: 'Command palette' })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: 'K', metaKey: true });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('ignores K on its own and other shortcuts', () => {
    render(<CommandPalette />);
    fireEvent.keyDown(window, { key: 'k' });
    fireEvent.keyDown(window, { key: 'j', ctrlKey: true });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('does not take Ctrl+K away from the rule editor', () => {
    render(<CommandPalette />);
    const editor = document.createElement('div');
    editor.className = 'monaco-editor';
    const inner = document.createElement('textarea');
    editor.appendChild(inner);
    document.body.appendChild(editor);
    fireEvent.keyDown(inner, { key: 'k', ctrlKey: true });
    expect(screen.queryByRole('dialog')).toBeNull();
    editor.remove();
  });

  it('lists the pages and the quick actions', () => {
    openIt();
    for (const label of ['SOC Dashboard', 'Alerts', 'Cases', 'Hunt', 'Detection Rules', 'Threat Intel', 'Connectors', 'Settings', 'ACORN Setup Guide']) expect(screen.getByText(label)).toBeInTheDocument();
    for (const label of ['Ask Leafy', 'Open Leafy page', 'Refresh data', 'Copy current URL']) expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText('Navigation')).toBeInTheDocument();
    expect(screen.getByText('Quick actions')).toBeInTheDocument();
  });

  it('choosing a page goes there and closes the palette', async () => {
    openIt();
    await userEvent.click(screen.getByText('Cases'));
    expect(nav.push).toHaveBeenCalledWith('/cases');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('typing narrows the list, matching on the extra keywords too', async () => {
    openIt();
    await userEvent.type(screen.getByPlaceholderText(/Search anything/), 'sigma');
    expect(screen.getByText('Detection Rules')).toBeInTheDocument();
    expect(screen.queryByText('Cases')).toBeNull();
  });

  it('says so when nothing matches', async () => {
    openIt();
    await userEvent.type(screen.getByPlaceholderText(/Search anything/), 'zzzzqqq');
    expect(await screen.findByText(/No matches/)).toBeInTheDocument();
  });

  it('the Copilot action tells the dock to open and closes the palette', async () => {
    const heard = vi.fn();
    window.addEventListener('aisoc:open-copilot', heard);
    openIt();
    await userEvent.click(screen.getByText('Ask Leafy'));
    expect(heard).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('dialog')).toBeNull();
    window.removeEventListener('aisoc:open-copilot', heard);
  });

  it('Copy current URL copies the address and says so, or says it could not', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    openIt();
    await userEvent.click(screen.getByText('Copy current URL'));
    expect(writeText).toHaveBeenCalledWith(window.location.href);
    expect(toast.success).toHaveBeenCalledWith('URL copied to clipboard');
    writeText.mockRejectedValueOnce(new Error('denied'));
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    await userEvent.click(screen.getByText('Copy current URL'));
    expect(toast.error).toHaveBeenCalledWith('Could not copy URL');
  });

  it('the backdrop closes it', async () => {
    openIt();
    await userEvent.click(screen.getByRole('button', { name: 'Close command palette' }));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('remembers pages visited (newest first, no repeats, at most five) but not the home or login pages', () => {
    const { rerender } = render(<CommandPalette />);
    for (const p of ['/', '/login', '/cases', '/alerts', '/cases', '/hunt', '/explore', '/graph', '/copilot']) {
      nav.pathname = p;
      rerender(<CommandPalette />);
    }
    expect(JSON.parse(localStorage.getItem(KEY) as string)).toEqual(['/copilot', '/graph', '/explore', '/hunt', '/cases']);
  });

  it('shows recent pages, leaving out the one you are on, with the page name where it is known', () => {
    localStorage.setItem(KEY, JSON.stringify(['/alerts', '/cases/1234', '/some/other/place']));
    nav.pathname = '/alerts';
    openIt();
    expect(screen.getByText('Recent pages')).toBeInTheDocument();
    const cases = screen.getByText('/cases/1234').parentElement as HTMLElement;
    expect(cases).toHaveTextContent('Cases');
    expect(screen.getAllByText('/some/other/place')).toHaveLength(2);
    expect(screen.queryAllByText('/alerts')).toHaveLength(1);
  });

  it('a damaged recent list is ignored rather than crashing the palette', () => {
    for (const bad of ['{not json', '"text"', '[1,2,{"a":1}]', 'null']) {
      localStorage.setItem(KEY, bad);
      const { unmount } = render(<CommandPalette />);
      fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
      expect(screen.getByRole('dialog')).toBeInTheDocument();
      expect(screen.queryByText('Recent pages')).toBeNull();
      unmount();
    }
  });

  it('removes its key listener when it goes away', () => {
    const { unmount } = render(<CommandPalette />);
    unmount();
    act(() => {
      fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    });
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});


describe('CommandPalette search', () => {
  const hit = (over: Record<string, unknown> = {}) => ({ kind: 'alert', id: 'a1', title: 'Impossible travel for jdoe', detail: 'high · new', client: 'Waterloo Sparkling Water Corp.', client_id: 'c1', ...over });
  const type = async (text: string) => userEvent.type(screen.getByPlaceholderText(/Search anything/), text);

  it('does not ask the server for fewer than two characters', async () => {
    openIt();
    await type('w');
    await new Promise((r) => setTimeout(r, 400));
    expect(searchApi.search).not.toHaveBeenCalled();
  });

  it('shows what the server finds, with its kind and client, and opens the page that shows it', async () => {
    searchApi.search.mockResolvedValue({ query: 'waterloo', hits: [hit(), hit({ kind: 'device', id: 'd1', title: 'WSW-PC-01', detail: 'SN123', client_id: 'c1' })] });
    openIt();
    await type('waterloo');
    expect(await screen.findByText('Impossible travel for jdoe')).toBeInTheDocument();
    expect(searchApi.search).toHaveBeenCalledTimes(1);
    expect(searchApi.search).toHaveBeenCalledWith('waterloo');
    expect(screen.getByText('WSW-PC-01')).toBeInTheDocument();
    expect(screen.getAllByText('Waterloo Sparkling Water Corp.').length).toBeGreaterThan(0);
    await userEvent.click(screen.getByText('WSW-PC-01'));
    expect(nav.push).toHaveBeenCalledWith('/devices?search=WSW-PC-01');
  });

  it('waits for a pause in typing instead of asking on every key', async () => {
    openIt();
    await type('router');
    await waitFor(() => expect(searchApi.search).toHaveBeenCalled());
    expect(searchApi.search).toHaveBeenCalledTimes(1);
    expect(searchApi.search).toHaveBeenLastCalledWith('router');
  });

  it('an answer to a question that has since changed is ignored', async () => {
    let first: (v: unknown) => void = () => {};
    searchApi.search.mockImplementationOnce(() => new Promise((resolve) => (first = resolve)));
    searchApi.search.mockResolvedValueOnce({ query: 'routers', hits: [hit({ id: 'new', title: 'Newer answer' })] });
    openIt();
    await type('router');
    await waitFor(() => expect(searchApi.search).toHaveBeenCalledTimes(1));
    await type('s');
    expect(await screen.findByText('Newer answer')).toBeInTheDocument();
    await act(async () => first({ query: 'router', hits: [hit({ id: 'old', title: 'Older answer' })] }));
    expect(screen.queryByText('Older answer')).toBeNull();
    expect(screen.getByText('Newer answer')).toBeInTheDocument();
  });

  it('says so when search is not answering, and pages and actions still work', async () => {
    searchApi.search.mockRejectedValue(new Error('500'));
    openIt();
    await type('router');
    expect(await screen.findByTestId('palette-search-error')).toHaveTextContent('Pages and actions still work');
    await userEvent.clear(screen.getByPlaceholderText(/Search anything/));
    expect(await screen.findByText('Alerts')).toBeInTheDocument();
  });

  it('each kind opens the page that shows it', () => {
    expect(hitHref(hit() as never)).toBe('/alerts/a1');
    expect(hitHref(hit({ kind: 'case', id: 'k1' }) as never)).toBe('/cases/k1');
    expect(hitHref(hit({ kind: 'stock', title: 'Dell Pro 16' }) as never)).toBe('/inventory?search=Dell%20Pro%2016');
    expect(hitHref(hit({ kind: 'nuc', title: 'NUC-1' }) as never)).toBe('/inventory?kind=nuc&search=NUC-1');
    expect(hitHref(hit({ kind: 'client', id: 'c9' }) as never)).toBe('/inventory?client=c9');
    expect(hitHref(hit({ kind: 'person', id: 'amy@acme.com', client_id: 'c1' }) as never)).toBe('/identities?client=c1&search=amy%40acme.com');
    expect(hitHref(hit({ kind: 'person', id: 'me@liveoak.example', client_id: null }) as never)).toBe('/identities?search=me%40liveoak.example');
    expect(hitHref(hit({ kind: 'alert', id: 'a/b' }) as never)).toBe('/alerts/a%2Fb');
  });
});
