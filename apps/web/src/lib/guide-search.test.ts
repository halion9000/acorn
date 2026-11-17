import { describe, expect, it } from 'vitest';
import { USER_GUIDE } from '@/content/user-guide';
import { parseGuide } from '@/lib/guide-markdown';
import { guideHits, guideSections, MAX_GUIDE_HITS } from '@/lib/guide-search';

const sections = parseGuide(['# G', '## 1. Alerts', 'Alerts show what the tools found. Retention is how long they are kept.', '## 2. Devices', 'Devices come from **NinjaOne** and `Addigy`.', '## 3. Other', 'Nothing here.'].join('\n')).sections;

describe('searching the guide from Settings', () => {
  it('finds the sections that contain every word, with a snippet around the first one, in guide order', () => {
    const hits = guideHits(sections, 'retention');
    expect(hits).toEqual([{ id: 'alerts', title: 'Alerts', snippet: expect.stringContaining('Retention is how long') }]);
    expect(guideHits(sections, 'devices ninjaone').map((h) => h.title)).toEqual(['Devices']);
    expect(guideHits(sections, 'alerts devices')).toEqual([]);
    expect(guideHits(sections, 'DEVICES')[0]!.snippet).toContain('NinjaOne and Addigy');
  });

  it('finds nothing for a very short or empty query, and caps the list', () => {
    expect(guideHits(sections, '')).toEqual([]);
    expect(guideHits(sections, 'a')).toEqual([]);
    const many = Array.from({ length: 12 }, (_, i) => ({ id: `s${i}`, title: `S${i}`, blocks: [{ type: 'p' as const, text: 'common word' }] }));
    expect(guideHits(many as never, 'common')).toHaveLength(MAX_GUIDE_HITS);
  });

  it('finds real text in the real guide', () => {
    const hits = guideHits(guideSections(USER_GUIDE), 'Ctrl+K');
    expect(hits.length).toBeGreaterThan(0);
    expect(hits.every((h) => h.id && h.title && h.snippet)).toBe(true);
  });
});
