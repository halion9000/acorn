import { describe, expect, it } from 'vitest';

import { failureDetail } from './failure-detail';

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

describe('failureDetail', () => {
  it('prefers a string detail, ignores non-string ones', async () => {
    expect(await failureDetail(json(400, { detail: 'nope' }))).toBe('nope');
    expect(await failureDetail(json(422, { detail: [{ msg: 'x' }] }))).toBe('HTTP 422');
    expect(await failureDetail(json(500, { detail: '' }))).toBe('HTTP 500');
  });

  it('falls back to the status when the body is not JSON', async () => {
    expect(await failureDetail(new Response('boom', { status: 502 }))).toBe('HTTP 502');
  });
});
