import { describe, expect, it } from 'vitest';
import { PAGE_WORDS, paletteNavItems } from './paletteNav';
import { NAV_CATALOG } from './Sidebar';

const curated = [{ label: 'Cases', href: '/cases', keywords: ['tickets'] }];

describe('paletteNavItems', () => {
  it('keeps the curated entries first, adds each other sidebar page once with its other words, and adds words to a curated page too', () => {
    const sections = [
      { items: [{ label: 'Cases', href: '/cases' }, { label: 'Licences & Counts', href: '/settings/billing' }] },
      { items: [{ label: 'Licences & Counts', href: '/settings/billing' }, { label: 'Odd page', href: '/odd' }] },
    ];
    const out = paletteNavItems(curated, sections);
    expect(out.map((o) => o.href)).toEqual(['/cases', '/settings/billing', '/odd']);
    expect(out[1].keywords).toContain('invoice');
    expect(out[2].keywords).toEqual([]);
    const withWords = paletteNavItems([{ label: 'Inventory', href: '/inventory', keywords: ['stock'] }], []);
    expect(withWords[0].keywords).toEqual(['stock', ...PAGE_WORDS['/inventory'].filter((w) => w !== 'stock')]);
  });

  it('a page the role hides is simply not in the sections, so it is not offered', () => {
    expect(paletteNavItems(curated, [{ items: [] }]).map((o) => o.href)).toEqual(['/cases']);
  });

  it('every page given extra words really is a sidebar page (a renamed address would silently lose them)', () => {
    const real = new Set(NAV_CATALOG.flatMap((s) => s.items.map((i) => i.href)));
    for (const href of Object.keys(PAGE_WORDS)) expect(real.has(href), href).toBe(true);
  });
});

describe('settings pages in the palette', () => {
  it('adds each settings page once after the sidebar pages, findable by a word of its description, and skips one already listed', () => {
    const out = paletteNavItems(
      [{ label: 'Audit Log', href: '/settings/audit', keywords: ['activity'] }],
      [{ items: [{ label: 'Cases', href: '/cases' }] }],
      [
        { href: '/settings/audit', label: 'Audit log', description: 'Every administrative and security event' },
        { href: '/settings/retention', label: 'Data retention', description: 'What is kept, for how long' },
      ],
    );
    expect(out.map((o) => o.href)).toEqual(['/settings/audit', '/cases', '/settings/retention']);
    expect(out[2].label).toBe('Data retention');
    expect(out[2].keywords).toContain('what is kept, for how long');
  });
});

describe('rememberSearch', () => {
  it('puts the newest first, drops an earlier copy whatever its case, and keeps five', async () => {
    const { rememberSearch } = await import('./paletteNav');
    expect(rememberSearch(['mfa', 'billing'], 'Billing ')).toEqual(['Billing', 'mfa']);
    expect(rememberSearch(['a1', 'b2', 'c3', 'd4', 'e5'], 'f6')).toEqual(['f6', 'a1', 'b2', 'c3', 'd4']);
  });
  it('does not remember a blank or one-letter search, and leaves the given list alone', async () => {
    const { rememberSearch } = await import('./paletteNav');
    const list = ['mfa'];
    expect(rememberSearch(list, ' ')).toEqual(['mfa']);
    expect(rememberSearch(list, 'x')).toEqual(['mfa']);
    expect(rememberSearch(list, 'dmarc')).toEqual(['dmarc', 'mfa']);
    expect(list).toEqual(['mfa']);
  });
});

describe('every page can be found by more than its one name', () => {
  it('searchWords gives each distinct word of the name and the other words, in lower case, without one-letter words', async () => {
    const { searchWords } = await import('./paletteNav');
    expect(searchWords({ label: 'Licences & Counts', href: '/x', keywords: ['billing', 'Counts', 'a b'] })).toEqual(['licences', 'counts', 'billing']);
  });

  it('every page the palette lists (curated, sidebar and settings pages) answers to at least two words', async () => {
    const { CURATED_PAGES, searchWords } = await import('./paletteNav');
    const { MORE_SETTINGS } = await import('@/components/settings/moreSettings');
    const thin = paletteNavItems(CURATED_PAGES, NAV_CATALOG, MORE_SETTINGS)
      .filter((item) => searchWords(item).length < 2)
      .map((item) => `${item.label} (${item.href})`);
    expect(thin).toEqual([]);
  });
});
