import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { AnnouncementBanner, visibleAnnouncements } from './AnnouncementBanner';

const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));
const a = (id: string, message: string, tone = 'info') => ({ id, message, tone, ends_on: null });

describe('which announcements show', () => {
  it('drops the dismissed, the empty and anything that is not an announcement, and keeps at most five', () => {
    expect(visibleAnnouncements([a('1', 'one'), a('2', '  '), a('3', 'three'), { id: 4 }, null], ['3']).map((x) => x.id)).toEqual(['1']);
    expect(visibleAnnouncements('nope', [])).toEqual([]);
    expect(visibleAnnouncements(Array.from({ length: 9 }, (_, i) => a(String(i), 'm')), [])).toHaveLength(5);
  });
});

describe('the announcement banner', () => {
  beforeEach(() => {
    authFetch.mockReset();
    window.sessionStorage.clear();
  });

  it('shows each live announcement as text with its tone and hides one for the session when dismissed', async () => {
    authFetch.mockImplementation(() => json([a('1', 'Maintenance tonight <b>9pm</b>', 'warning'), a('2', 'Welcome to the new Calendar')]));
    render(<AnnouncementBanner />);
    const warning = await screen.findByText('Maintenance tonight <b>9pm</b>');
    expect(warning.closest('[role="status"]')).toHaveAttribute('data-tone', 'warning');
    expect(document.querySelector('b')).toBeNull();
    await userEvent.click(screen.getAllByRole('button', { name: 'Dismiss' })[0]!);
    expect(screen.queryByText(/Maintenance tonight/)).toBeNull();
    expect(screen.getByText('Welcome to the new Calendar')).toBeInTheDocument();
    expect(JSON.parse(window.sessionStorage.getItem('aisoc.announcements.dismissed') ?? '[]')).toEqual(['1']);
  });

  it('stays hidden after a reload once dismissed, and shows nothing when there is nothing or the list is refused', async () => {
    window.sessionStorage.setItem('aisoc.announcements.dismissed', JSON.stringify(['1']));
    authFetch.mockImplementation(() => json([a('1', 'Old news')]));
    const first = render(<AnnouncementBanner />);
    await waitFor(() => expect(authFetch).toHaveBeenCalled());
    expect(screen.queryByText('Old news')).toBeNull();
    first.unmount();
    authFetch.mockImplementation(() => json({}, 403));
    const second = render(<AnnouncementBanner />);
    await waitFor(() => expect(authFetch).toHaveBeenCalledTimes(2));
    expect(second.container.textContent).toBe('');
  });
});
