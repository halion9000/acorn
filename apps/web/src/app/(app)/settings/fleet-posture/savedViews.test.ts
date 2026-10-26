import { describe, expect, it } from 'vitest';
import { addView, MAX_VIEWS, parseViews, removeView, type SavedView } from './savedViews';

describe('saved views', () => {
  it('reads a stored list, keeps only the setting each view can have, and drops damaged entries', () => {
    const raw = JSON.stringify([
      { name: ' Last week ', tab: 'changes', days: 7 },
      { name: 'Hosts', tab: 'search', q: 'SRV-02', days: 99 },
      { name: '', tab: 'worst' },
      { name: 'No tab' },
      'junk',
      null,
      { name: 'Last week', tab: 'worst' },
    ]);
    const views = parseViews(raw);
    expect(views.map((v) => v.name)).toEqual(['Last week', 'Hosts']);
    expect(views[0]).toEqual({ name: 'Last week', tab: 'changes', days: 7 });
    expect(views[1]).toEqual({ name: 'Hosts', tab: 'search', q: 'SRV-02' });
  });

  it('gives nothing for nothing, text that is not JSON, or JSON that is not a list', () => {
    expect(parseViews(null)).toEqual([]);
    expect(parseViews('{broken')).toEqual([]);
    expect(parseViews('{"a":1}')).toEqual([]);
  });

  it('adds a view, replaces one with the same name in place, refuses a blank name and stops at the limit', () => {
    let v = addView([], { name: 'A', tab: 'worst' });
    v = addView(v, { name: 'B', tab: 'changes', days: 30 });
    v = addView(v, { name: 'A', tab: 'tools' });
    expect(v).toEqual([{ name: 'A', tab: 'tools' }, { name: 'B', tab: 'changes', days: 30 }]);
    expect(addView(v, { name: '  ', tab: 'worst' })).toBe(v);
    let full: SavedView[] = [];
    for (let i = 0; i < MAX_VIEWS + 3; i++) full = addView(full, { name: `v${i}`, tab: 'worst' });
    expect(full).toHaveLength(MAX_VIEWS);
    expect(addView(full, { name: 'v0', tab: 'tools' })[0].tab).toBe('tools');
  });

  it('removes a view by name', () => {
    expect(removeView([{ name: 'A', tab: 'worst' }, { name: 'B', tab: 'worst' }], 'A')).toEqual([{ name: 'B', tab: 'worst' }]);
  });
});
