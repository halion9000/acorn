import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

let path = '/devices';
vi.mock('next/navigation', () => ({ usePathname: () => path }));
vi.mock('next/link', () => ({
  default: ({ children, href, className, prefetch }: { children: React.ReactNode; href: string; className?: string; prefetch?: boolean }) => (
    <a href={href} className={className} data-prefetch={String(prefetch)}>
      {children}
    </a>
  ),
}));

import { Sidebar, filterSections } from './Sidebar';

const nav = () => screen.getByRole('navigation', { name: 'Main navigation' });
const groupButtons = () => within(nav()).getAllByRole('button').filter((b) => b.hasAttribute('aria-expanded'));

beforeEach(() => {
  window.localStorage.clear();
  path = '/devices';
});
afterEach(() => cleanup());

describe('filterSections', () => {
  const sections = [
    { title: 'A', items: [{ label: 'Devices', href: '/devices', icon: null }, { label: 'Alerts', href: '/alerts', icon: null }] },
    { title: 'B', items: [{ label: 'Cases', href: '/cases', icon: null }] },
  ];
  it('keeps the items that match, ignoring case, drops an empty section, and keeps all for an empty filter', () => {
    expect(filterSections(sections, 'DEV').map((s) => s.items.map((i) => i.label))).toEqual([['Devices']]);
    expect(filterSections(sections, 'zzz')).toEqual([]);
    expect(filterSections(sections, '  ')).toBe(sections);
  });
});

describe('Sidebar', () => {
  it('does not prefetch its pages', () => {
    render(<Sidebar />);
    const links = within(nav()).getAllByRole('link');
    expect(links.length).toBeGreaterThan(20);
    expect(links.every((a) => a.getAttribute('data-prefetch') === 'false')).toBe(true);
  });

  it('filters the menu as you type and says so when nothing matches', async () => {
    render(<Sidebar />);
    await userEvent.type(screen.getByLabelText('Filter the menu'), 'devices');
    const links = within(nav()).getAllByRole('link').map((a) => a.getAttribute('href'));
    expect(links).toContain('/devices');
    expect(links).not.toContain('/alerts');
    await userEvent.clear(screen.getByLabelText('Filter the menu'));
    await userEvent.type(screen.getByLabelText('Filter the menu'), 'qqqqq');
    expect(screen.getByText('Nothing in the menu matches.')).toBeTruthy();
  });

  it('closes a group, remembers it for the next visit, and keeps the group of the current page open', async () => {
    render(<Sidebar />);
    const groups = groupButtons();
    expect(groups.length).toBeGreaterThan(3);
    const other = groups.find((g) => g.getAttribute('aria-expanded') === 'true' && !within(g.parentElement as HTMLElement).queryByRole('link', { current: undefined, name: /Devices/ }));
    expect(other).toBeTruthy();
    const title = other!.textContent!.replace(/[−+]/g, '').trim();
    const before = within(nav()).getAllByRole('link').length;
    await userEvent.click(other!);
    expect(within(nav()).getAllByRole('link').length).toBeLessThan(before);
    expect(JSON.parse(window.localStorage.getItem('acorn.nav.collapsed.v1') ?? '[]')).toContain(title);
    cleanup();
    render(<Sidebar />);
    const again = groupButtons().find((g) => g.textContent!.includes(title));
    expect(again?.getAttribute('aria-expanded')).toBe('false');
    const holder = groupButtons().find((g) => within(g.parentElement as HTMLElement).queryByRole('link', { name: /^Devices/ }));
    expect(holder?.getAttribute('aria-expanded')).toBe('true');
  });
});
