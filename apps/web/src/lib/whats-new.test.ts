import { describe, expect, it } from 'vitest';
import { USER_GUIDE } from '@/content/user-guide';
import { groupByDate, parseWhatsNew, plainEntry } from '@/lib/whats-new';

const GUIDE = [
  '# Guide',
  '**Reading the status notes.** Features marked **(new, 2026-10-19)** were added in October.',
  '## 3. Connecting tools in CORE',
  '- **CIPP (new, 2026-10-19).** Connected through an Entra app.',
  '- Plain old entry with no tag.',
  '## 5. Alerts',
  '- **Search (new, API only, 2026-11-12).** Finds `alerts` and *cases*.',
  '- Another one (new) with no date.',
  '- **Second on the day (new, 2026-11-12).** Later in the guide.',
  '### Not a section (new, 2026-11-20)',
].join('\n');

describe("what's new", () => {
  it('lists dated-new lines newest first, with their section, and leaves out undated tags, plain lines and headings', () => {
    const e = parseWhatsNew(GUIDE);
    expect(e.map((x) => [x.date, x.section])).toEqual([
      ['2026-11-12', 'Alerts'],
      ['2026-11-12', 'Alerts'],
      ['2026-10-19', 'Connecting tools in CORE'],
    ]);
    expect(e[0]!.sectionId).toBe('alerts');
    expect(e[0]!.text).toBe('Search. Finds alerts and cases.');
    expect(e[1]!.text).toContain('Second on the day');
  });

  it('reads the real guide: every entry has a date, some words and a section, in date order', () => {
    const e = parseWhatsNew(USER_GUIDE);
    expect(e.length).toBeGreaterThan(5);
    for (const x of e) {
      expect(x.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(x.text.length).toBeGreaterThan(3);
      expect(x.text).not.toMatch(/\(new/);
    }
    expect(e.map((x) => x.date)).toEqual([...e.map((x) => x.date)].sort().reverse());
  });

  it('groups by date and cuts a long entry at a word', () => {
    expect(groupByDate(parseWhatsNew(GUIDE)).map((g) => [g.date, g.entries.length])).toEqual([['2026-11-12', 2], ['2026-10-19', 1]]);
    const long = plainEntry(`- ${'word '.repeat(100)}(new, 2026-11-12)`);
    expect(long.length).toBeLessThanOrEqual(281);
    expect(long.endsWith('…')).toBe(true);
    expect(plainEntry('- **Bold** and `code`')).toBe('Bold and code');
  });
});
