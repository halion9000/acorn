import { describe, expect, it } from 'vitest';

import { asNumber, compareValues, nextSort, sortArrow, sortedBy } from './tableSort';

describe('which values are numbers', () => {
  it('reads numbers and numbers written as text, and nothing else', () => {
    expect([asNumber(4), asNumber('12.50'), asNumber(' 3 '), asNumber('-7'), asNumber('1,250.5'), asNumber('.5')]).toEqual([4, 12.5, 3, -7, 1250.5, 0.5]);
    expect([asNumber('Acme'), asNumber(''), asNumber('3 h'), asNumber(null), asNumber(undefined), asNumber(NaN), asNumber(Infinity), asNumber('1e3')]).toEqual([null, null, null, null, null, null, null, null]);
  });
});

describe('sorting', () => {
  it('puts money sent as text in numeric order, the way 977.12 belongs under 9810.27 and 9820.00 and not between them', () => {
    const rows = ['9820.00', '977.12', '9810.27', '91.56', '8312.77', '904.80'].map((revenue) => ({ revenue }));
    const desc = sortedBy(rows, (r) => r.revenue, true).map((r) => r.revenue);
    expect(desc).toEqual(['9820.00', '9810.27', '8312.77', '977.12', '904.80', '91.56']);
    expect(sortedBy(rows, (r) => r.revenue, false).map((r) => r.revenue)).toEqual([...desc].reverse());
  });

  it('compares numbers and numbers-as-text with each other, and names without regard to case', () => {
    expect(compareValues(10, '9.5')).toBeGreaterThan(0);
    expect(compareValues('b', 'A')).toBeGreaterThan(0);
    expect(sortedBy([{ n: 'beta' }, { n: 'Alpha' }, { n: 'charlie' }], (r) => r.n, false).map((r) => r.n)).toEqual(['Alpha', 'beta', 'charlie']);
    expect(sortedBy([{ n: 'PC-10' }, { n: 'PC-9' }, { n: 'PC-100' }], (r) => r.n, false).map((r) => r.n)).toEqual(['PC-9', 'PC-10', 'PC-100']);
  });

  it('leaves empty values last whichever way it goes, keeps ties in their order and does not change the list it is given', () => {
    const rows = [{ id: 'a', v: null }, { id: 'b', v: 5 }, { id: 'c', v: '' }, { id: 'd', v: 5 }, { id: 'e', v: 9 }, { id: 'f', v: NaN }];
    const original = [...rows];
    expect(sortedBy(rows, (r) => r.v, true).map((r) => r.id)).toEqual(['e', 'b', 'd', 'a', 'c', 'f']);
    expect(sortedBy(rows, (r) => r.v, false).map((r) => r.id)).toEqual(['b', 'd', 'e', 'a', 'c', 'f']);
    expect(rows).toEqual(original);
  });
});

describe('the header state', () => {
  it('starts a figure column high to low and a name column A to Z, and flips the one already sorted', () => {
    expect(nextSort(null, 'revenue')).toEqual({ key: 'revenue', desc: true });
    expect(nextSort(null, 'client', true)).toEqual({ key: 'client', desc: false });
    expect(nextSort({ key: 'revenue', desc: true }, 'revenue')).toEqual({ key: 'revenue', desc: false });
    expect(nextSort({ key: 'revenue', desc: false }, 'hours')).toEqual({ key: 'hours', desc: true });
  });
  it('shows an arrow on the sorted column only', () => {
    expect(sortArrow({ key: 'revenue', desc: true }, 'revenue')).toBe(' ↓');
    expect(sortArrow({ key: 'revenue', desc: false }, 'revenue')).toBe(' ↑');
    expect(sortArrow({ key: 'revenue', desc: false }, 'hours')).toBe('');
    expect(sortArrow(null, 'hours')).toBe('');
  });
});
