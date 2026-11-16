import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { USER_GUIDE } from '@/content/user-guide';
import { parseWhatsNew } from '@/lib/whats-new';
import { WhatsNewView } from './WhatsNewView';

describe("What's new", () => {
  it('shows every dated entry of the guide under its date, each linking to its guide section', () => {
    render(<WhatsNewView />);
    const entries = parseWhatsNew(USER_GUIDE);
    const days = screen.getAllByTestId('whats-new-day');
    expect(days.length).toBeGreaterThan(0);
    expect(screen.getAllByRole('listitem')).toHaveLength(entries.length);
    const first = entries[0]!;
    expect(screen.getByText(first.date)).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: first.section })[0]).toHaveAttribute('href', `/settings/guide#${first.sectionId}`);
  });
});
