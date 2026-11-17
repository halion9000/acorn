import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { USER_GUIDE } from '@/content/user-guide';
import { guideHits, guideSections } from '@/lib/guide-search';
import { SettingsGuideHits } from './SettingsGuideHits';

describe('Settings search: in the guide', () => {
  it('lists each guide section that holds the words, linking to it with a snippet', () => {
    render(<SettingsGuideHits hits={guideHits(guideSections(USER_GUIDE), 'Ctrl+K')} />);
    const links = screen.getAllByRole('link');
    expect(links.length).toBeGreaterThan(0);
    expect(links.every((l) => /^\/settings\/guide#[a-z0-9-]+$/.test(l.getAttribute('href') ?? ''))).toBe(true);
    expect(screen.getByTestId('settings-guide-hits')).toHaveTextContent(/Ctrl\+K/i);
  });
  it('draws nothing when the guide has nothing', () => {
    const { container } = render(<SettingsGuideHits hits={[]} />);
    expect(container.textContent).toBe('');
  });
});
