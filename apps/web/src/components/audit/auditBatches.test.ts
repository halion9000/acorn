import { describe, expect, it } from 'vitest';
import { foldBatches } from './auditBatches';

const ev = (id: string, action: string, batch?: string) => ({ id, action, changes: batch === undefined ? null : { batch } });

describe('foldBatches', () => {
  it('folds events next to each other that share a batch and an action into one row with a count', () => {
    const rows = foldBatches([ev('1', 'alerts:bulk_close', 'b1'), ev('2', 'alerts:bulk_close', 'b1'), ev('3', 'alerts:bulk_close', 'b1'), ev('4', 'role:created'), ev('5', 'alerts:bulk_close', 'b2')]);
    expect(rows.map((r) => [r.event.id, r.count, r.batch])).toEqual([
      ['1', 3, 'b1'],
      ['4', 1, null],
      ['5', 1, 'b2'],
    ]);
  });

  it('does not fold across a different action or an event in between, and never folds events with no batch', () => {
    const rows = foldBatches([ev('1', 'alerts:bulk_close', 'b1'), ev('2', 'alerts:bulk_assign', 'b1'), ev('3', 'x:y'), ev('4', 'x:y'), ev('5', 'alerts:bulk_close', 'b1'), ev('6', 'alerts:bulk_close', '')]);
    expect(rows.map((r) => r.count)).toEqual([1, 1, 1, 1, 1, 1]);
  });

  it('leaves a batch unfolded when it is open, and keeps every event counted', () => {
    const items = [ev('1', 'a:b', 'b1'), ev('2', 'a:b', 'b1'), ev('3', 'a:b', 'b2'), ev('4', 'a:b', 'b2')];
    const rows = foldBatches(items, new Set(['b1']));
    expect(rows.map((r) => [r.event.id, r.count])).toEqual([['1', 1], ['2', 1], ['3', 2]]);
    expect(rows.reduce((n, r) => n + r.count, 0)).toBe(items.length);
    expect(foldBatches([])).toEqual([]);
  });
});
