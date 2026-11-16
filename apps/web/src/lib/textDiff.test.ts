import { describe, expect, it } from 'vitest';
import { diffCounts, lineDiff, MAX_PAIRS } from '@/lib/textDiff';

const show = (a: string, b: string) => lineDiff(a, b).map((l) => `${l.kind === 'same' ? ' ' : l.kind === 'add' ? '+' : '-'}${l.text}`);

describe('the line diff', () => {
  it('marks only the lines that changed, in reading order', () => {
    expect(show('one\ntwo\nthree', 'one\n2\nthree\nfour')).toEqual([' one', '-two', '+2', ' three', '+four']);
    expect(show('a\nb\nc', 'a\nc')).toEqual([' a', '-b', ' c']);
  });
  it('identical texts have no changes, and trailing spaces and line endings do not count as changes', () => {
    expect(diffCounts(lineDiff('a\nb', 'a\nb'))).toEqual({ added: 0, removed: 0 });
    expect(diffCounts(lineDiff('a  \r\nb', 'a\nb'))).toEqual({ added: 0, removed: 0 });
  });
  it('an empty side is all added or all removed', () => {
    expect(show('', 'x\ny')).toEqual(['+x', '+y']);
    expect(show('x', '')).toEqual(['-x']);
    expect(lineDiff('', '')).toEqual([]);
  });
  it('counts what was added and removed, and a very large pair is shown as replaced rather than compared', () => {
    expect(diffCounts(lineDiff('a\nb\nc', 'a\nx\ny\nc'))).toEqual({ added: 2, removed: 1 });
    const side = (n: number, p: string) => Array.from({ length: n }, (_, i) => `${p}${i}`).join('\n');
    const big = lineDiff(side(2100, 'o'), side(2100, 'n'));
    expect(2100 * 2100).toBeGreaterThan(MAX_PAIRS);
    expect(diffCounts(big)).toEqual({ added: 2100, removed: 2100 });
  });
});
