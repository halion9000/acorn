import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import CountryMap, { drawable, fillFor, shade } from './CountryMap';

const names = (c: string) => ({ US: 'United States', DE: 'Germany' })[c] ?? c;

describe('shade and fillFor', () => {
  it('shades by the logarithm so a very busy country does not wash out a quiet one, and never goes out of range', () => {
    expect(shade(0, 100)).toBe(0);
    expect(shade(100, 100)).toBeCloseTo(1);
    expect(shade(1, 1_000_000)).toBeGreaterThanOrEqual(0.25);
    expect(shade(10, 1_000_000)).toBeGreaterThan(shade(1, 1_000_000));
    expect(shade(5, 1000)).toBeGreaterThan(0.25);
  });

  it('draws a country with any failed mail amber and one with none blue', () => {
    expect(fillFor({ code: 'US', emails: 10, failed: 1 }, 10).fill).toBe('#f59e0b');
    expect(fillFor({ code: 'DE', emails: 10, failed: 0 }, 10).fill).toBe('#60a5fa');
  });
});

describe('CountryMap', () => {
  it('colours each country it has an outline for, with its numbers on hover, and leaves the rest grey', () => {
    render(<CountryMap countries={[{ code: 'US', emails: 40, failed: 2 }, { code: 'DE', emails: 10, failed: 0 }]} nameOf={names} />);
    const painted = screen.getAllByTestId('map-country');
    expect(painted.map((p) => p.getAttribute('data-code')).sort()).toEqual(['DE', 'US']);
    expect(painted.find((p) => p.getAttribute('data-code') === 'US')?.querySelector('title')?.textContent).toBe('United States: 40 messages, 2 failed');
    expect(painted.find((p) => p.getAttribute('data-code') === 'DE')?.querySelector('title')?.textContent).toBe('Germany: 10 messages, all pass');
    expect(screen.queryByTestId('map-left-off')).toBeNull();
  });

  it('says how many countries it could not draw, and draws nothing when none can be', () => {
    const countries = [{ code: 'US', emails: 5, failed: 0 }, { code: 'ZZ', emails: 3, failed: 0 }];
    expect(drawable(countries)).toEqual({ shown: [countries[0]], left: 1 });
    const { unmount } = render(<CountryMap countries={countries} nameOf={names} />);
    expect(screen.getByTestId('map-left-off').textContent).toContain('1 small country is in the list only');
    unmount();
    render(<CountryMap countries={[{ code: 'ZZ', emails: 3, failed: 0 }]} nameOf={names} />);
    expect(screen.queryByTestId('country-map')).toBeNull();
  });

  it('ignores a country with no mail', () => {
    expect(drawable([{ code: 'US', emails: 0, failed: 0 }])).toEqual({ shown: [], left: 0 });
  });
});
