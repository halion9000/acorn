import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SWRConfig } from 'swr';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { DataRetention } from './DataRetention';

const show = () =>
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <DataRetention />
    </SWRConfig>,
  );

beforeEach(() => authFetch.mockReset());

describe('DataRetention', () => {
  it('shows each kind of data with how long it is kept and what ends it', async () => {
    authFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve([{ what: 'Alerts', kept: 'Kept until deleted by hand', ends: 'Nothing deletes alerts automatically.' }]) });
    show();
    expect(await screen.findByText('Kept until deleted by hand')).toBeInTheDocument();
    expect(screen.getByText('Nothing deletes alerts automatically.')).toBeInTheDocument();
  });
  it('says when it cannot load', async () => {
    authFetch.mockResolvedValue({ ok: false, status: 500, json: () => Promise.resolve({}) });
    show();
    expect(await screen.findByText('Could not load this page.')).toBeInTheDocument();
  });
});
