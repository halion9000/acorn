import { describe, expect, it } from 'vitest';
import { USER_GUIDE } from '@/content/user-guide';
import { ageNewTags, blockText, parseGuide, parseInline, searchSections, slugOf } from './guide-markdown';

describe('slugOf', () => {
  it('drops the number and joins the words', () => {
    expect(slugOf('3. Connecting tools in CORE')).toBe('connecting-tools-in-core');
    expect(slugOf('9. Identity (all new, from CIPP through CORE)')).toBe('identity-all-new-from-cipp-through-core');
  });
});

describe('parseInline', () => {
  it('splits bold, italic and code', () => {
    expect(parseInline('a **b** `c` *d* e')).toEqual([
      { kind: 'text', text: 'a ' },
      { kind: 'b', text: 'b' },
      { kind: 'text', text: ' ' },
      { kind: 'code', text: 'c' },
      { kind: 'text', text: ' ' },
      { kind: 'i', text: 'd' },
      { kind: 'text', text: ' e' },
    ]);
  });

  it('turns the (new) tags into their own pieces, also inside bold', () => {
    expect(parseInline('Sign-ins **(new)** and X (new, API only) end')).toEqual([
      { kind: 'text', text: 'Sign-ins ' },
      { kind: 'new', text: 'new' },
      { kind: 'text', text: ' and X ' },
      { kind: 'new', text: 'new, API only' },
      { kind: 'text', text: ' end' },
    ]);
  });

  it('leaves an unmatched marker as plain text and never produces markup', () => {
    expect(parseInline('2 * 3 and <b>x</b>')).toEqual([{ kind: 'text', text: '2 * 3 and <b>x</b>' }]);
  });

  it('finds code inside italics and bold', () => {
    expect(parseInline('*see `x` now*')).toEqual([
      { kind: 'i', text: 'see ' },
      { kind: 'code', text: 'x' },
      { kind: 'i', text: ' now' },
    ]);
    expect(parseInline('**run `y`**')).toEqual([
      { kind: 'b', text: 'run ' },
      { kind: 'code', text: 'y' },
    ]);
  });

  it('keeps `*` inside code as code', () => {
    expect(parseInline('use `a*b` here')).toEqual([
      { kind: 'text', text: 'use ' },
      { kind: 'code', text: 'a*b' },
      { kind: 'text', text: ' here' },
    ]);
  });
});

describe('parseGuide', () => {
  const md = ['# Title', '', 'Intro line one', 'continues.', '', '## 1. First', '', '- a', '- b', '', '1. one', '2. two', '', '| H1 | H2 |', '|---|---|', '| x | y |', '| z | w |', '', '---', '', '### Sub', 'text'].join('\n');

  it('reads the title, intro, sections, lists, tables, rules and sub-headings', () => {
    const g = parseGuide(md);
    expect(g.title).toBe('Title');
    expect(g.intro).toEqual([{ type: 'p', text: 'Intro line one continues.' }]);
    expect(g.sections).toHaveLength(1);
    expect(g.sections[0].id).toBe('first');
    expect(g.sections[0].blocks).toEqual([
      { type: 'ul', items: ['a', 'b'] },
      { type: 'ol', items: ['one', 'two'] },
      { type: 'table', head: ['H1', 'H2'], rows: [['x', 'y'], ['z', 'w']] },
      { type: 'hr' },
      { type: 'h3', text: 'Sub' },
      { type: 'p', text: 'text' },
    ]);
  });
});

describe('searchSections', () => {
  const g = parseGuide('## One\n\nalpha beta\n\n## Two\n\n| A | B |\n|---|---|\n| gamma | delta |\n');
  it('keeps every section for an empty search', () => {
    expect(searchSections(g.sections, '  ')).toHaveLength(2);
  });
  it('finds a section by any word in it, case-insensitively, including inside a table', () => {
    expect(searchSections(g.sections, 'ALPHA').map((s) => s.title)).toEqual(['One']);
    expect(searchSections(g.sections, 'delta').map((s) => s.title)).toEqual(['Two']);
  });
  it('needs every word to be there', () => {
    expect(searchSections(g.sections, 'alpha gamma')).toEqual([]);
  });
  it('reads a block as plain text', () => {
    expect(blockText({ type: 'ul', items: ['x', 'y'] })).toBe('x y');
  });
});

describe('the real user guide', () => {
  const g = parseGuide(USER_GUIDE);

  it('has all fifteen numbered sections, in order', () => {
    expect(g.sections.map((s) => s.title.split('.')[0])).toEqual(Array.from({ length: 15 }, (_, i) => String(i + 1)));
  });

  it('has unique anchors for the contents list', () => {
    const ids = g.sections.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('leaves no stray markdown in the text it will show', () => {
    const shown = [...g.intro, ...g.sections.flatMap((s) => s.blocks)].flatMap((b) => {
      const pieces: string[] = b.type === 'table' ? [...b.head, ...b.rows.flat()] : b.type === 'ul' || b.type === 'ol' ? b.items : b.type === 'hr' ? [] : [b.text];
      return pieces.flatMap((t) => parseInline(t)).filter((p) => p.kind === 'text' || p.kind === 'b' || p.kind === 'i');
    });
    for (const p of shown) {
      expect(p.text, p.text).not.toMatch(/\*\*|`/);
    }
  });

  it('turns every table row into the same number of cells as its header', () => {
    for (const s of g.sections) {
      for (const b of s.blocks) {
        if (b.type === 'table') for (const r of b.rows) expect(r.length, `${s.title}: ${r.join('|')}`).toBe(b.head.length);
      }
    }
  });

  it('can be searched for a feature', () => {
    expect(searchSections(g.sections, 'Hidden until online').map((s) => s.title.split('.')[0])).toContain('8');
  });
});

describe('dated (new) tags', () => {
  const line = '- **Sign-in history (new, 2026-11-01).** Text. Also **Labels (new, API only, 2026-11-10)** and an undated (new) one.';

  it('show as plain (new) for a month from their date, keeping any words between', () => {
    expect(ageNewTags(line, '2026-11-12')).toBe('- **Sign-in history (new).** Text. Also **Labels (new, API only)** and an undated (new) one.');
    expect(ageNewTags('X (new, 2026-11-01).', '2026-12-01')).toBe('X (new).');
  });

  it('are taken out, with the space before them, once the month has passed', () => {
    expect(ageNewTags(line, '2026-12-02')).toBe('- **Sign-in history.** Text. Also **Labels (new, API only)** and an undated (new) one.');
    expect(ageNewTags(line, '2027-01-15')).toBe('- **Sign-in history.** Text. Also **Labels** and an undated (new) one.');
  });

  it('leave an undated tag, a heading, and a date that is not one alone', () => {
    expect(ageNewTags('## 10. Client posture (new)', '2030-01-01')).toBe('## 10. Client posture (new)');
    expect(ageNewTags('### Additions (new, 2026-01-01)', '2030-01-01')).toBe('### Additions (new, 2026-01-01)');
    expect(ageNewTags('X (new, 2026-13-45) y', '2030-01-01')).toBe('X (new, 2026-13-45) y');
    expect(ageNewTags(line, 'not a date')).toBe(line);
  });

  it('the aged text parses into the same pieces as a hand-written (new)', () => {
    expect(parseInline(ageNewTags('**Labels (new, 2026-11-10).** Text', '2026-11-12'))).toEqual(parseInline('**Labels (new).** Text'));
  });
});

describe('the guide itself', () => {
  it('dates every (new) tag outside a heading, so each one drops off by itself', () => {
    const undated = USER_GUIDE.split('\n')
      .filter((line) => !line.startsWith('#'))
      .flatMap((line) => line.match(/\(new(?:,[^)]*)?\)/g) ?? [])
      .filter((tag) => !/, \d{4}-\d{2}-\d{2}\)$/.test(tag));
    expect(undated).toEqual([]);
  });

  it('shows no new badge outside headings once every date is more than a month old', () => {
    const later = ageNewTags(USER_GUIDE, '2030-01-01');
    const left = later.split('\n').filter((line) => !line.startsWith('#') && /\(new[,)]/.test(line));
    expect(left).toEqual([]);
    expect(later.length).toBeLessThan(USER_GUIDE.length);
  });
});
