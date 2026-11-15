import { describe, expect, it } from 'vitest';

import { reviewsOf } from './IdentitiesView';

describe('reviewsOf', () => {
  it('reads a person\'s reviews newest first and fills in what is missing', () => {
    const out = reviewsOf({ reviews: [{ date: '2026-10-01T00:00:00Z', rating: 'Okay', sentiment: 'neutral' }, { date: '2026-10-09T00:00:00Z', rating: 'Great', sentiment: 'positive', comment: 'Fast!', ticket_id: '509' }, { date: '2026-09-01T00:00:00Z', sentiment: 7 }] });
    expect(out.map((r) => r.date.slice(0, 10))).toEqual(['2026-10-09', '2026-10-01', '2026-09-01']);
    expect(out[0]).toEqual({ date: '2026-10-09T00:00:00Z', rating: 'Great', sentiment: 'positive', comment: 'Fast!', ticket_id: '509' });
    expect(out[1]).toMatchObject({ comment: '', ticket_id: '' });
    expect(out[2]!.sentiment).toBeNull();
  });
  it('gives nothing when SimpleSat said nothing or sent something else', () => {
    expect(reviewsOf(undefined)).toEqual([]);
    expect(reviewsOf({})).toEqual([]);
    expect(reviewsOf({ reviews: 'x' })).toEqual([]);
    expect(reviewsOf({ reviews: [null, 3] })).toEqual([]);
  });
});
