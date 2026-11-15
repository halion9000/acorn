import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { msspApi, sortClientsByName } from './api';

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });

beforeEach(() => window.localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe('client lists are in name order', () => {
  it('sorts by name without regard to case, with numbers in their natural order, and leaves the input alone', () => {
    const input = [{ name: 'burnett Turner' }, { name: 'Austin FC' }, { name: 'Client 10' }, { name: 'client 2' }, { name: 'A Pup Above, Inc.' }];
    expect(sortClientsByName(input).map((c) => c.name)).toEqual(['A Pup Above, Inc.', 'Austin FC', 'burnett Turner', 'client 2', 'Client 10']);
    expect(input[0]!.name).toBe('burnett Turner');
  });

  it('msspApi.listChildren hands back the clients sorted, whatever order the server sent', async () => {
    vi.stubGlobal('fetch', async () => json([{ id: '3', name: 'Light Sky Production LLC' }, { id: '1', name: 'American Academy of Nurse Practitioners' }, { id: '2', name: 'Austin FC' }]));
    const out = await msspApi.listChildren();
    expect(out.map((c) => c.id)).toEqual(['1', '2', '3']);
  });
});
