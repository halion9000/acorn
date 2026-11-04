import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ duplicates: vi.fn(), mergePeople: vi.fn(), separatePeople: vi.fn() }));
vi.mock('@/lib/api', () => ({ identitiesApi: api }));
vi.mock('@/components/mssp/ClientMapping', () => ({ vendorLabel: (v: string) => v.toUpperCase() }));

import { PossibleDuplicates, duplicateTitle } from './PossibleDuplicates';

const person = (email: string, over: Record<string, unknown> = {}) => ({
  key: `c1:${email}`,
  client_id: 'c1',
  client_name: 'Acme',
  email,
  display_name: 'Marla Falcon',
  kind: 'user',
  enabled: true,
  admin: false,
  licensed: false,
  mfa: 'unknown',
  mfa_methods: null,
  tools: ['cipp'],
  sources: [],
  open_alerts: 0,
  top_severity: null,
  ...over,
});
const pair = (over: Record<string, unknown> = {}) => ({
  client_id: 'c1',
  client_name: 'Acme',
  a: person('marla@a.com'),
  b: person('marla@b.com', { display_name: 'Marla Falcon @ B', tools: ['dropsuite', 'huntress'] }),
  score: 90,
  confidence: 'high',
  reasons: ['The same name: Marla Falcon', 'The same name before the @: marla'],
  both_licensed: false,
  ...over,
});

const show = (onChanged?: () => void) =>
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
      <PossibleDuplicates clientId="c1" onChanged={onChanged} />
    </SWRConfig>,
  );

beforeEach(() => {
  Object.values(api).forEach((m) => m.mockReset());
  api.duplicates.mockResolvedValue({ items: [pair()], total: 1 });
});

describe('the title', () => {
  it('counts the pairs in words', () => {
    expect([duplicateTitle(0), duplicateTitle(1), duplicateTitle(7)]).toEqual(['No possible duplicates found', '1 possible duplicate', '7 possible duplicates']);
  });
});

describe('Possible duplicates', () => {
  it('asks for the client being looked at and shows each pair with both people and the reasons', async () => {
    show();
    const card = await screen.findByTestId('duplicate-pair');
    expect(api.duplicates).toHaveBeenCalledWith('c1');
    expect(await screen.findByText('1 possible duplicate')).toBeInTheDocument();
    expect(card).toHaveTextContent('Acme');
    expect(card).toHaveTextContent('Likely the same person');
    expect(card).toHaveTextContent('marla@a.com');
    expect(card).toHaveTextContent('marla@b.com');
    expect(card).toHaveTextContent('CIPP');
    expect(card).toHaveTextContent('DROPSUITE, HUNTRESS');
    expect(card).toHaveTextContent('The same name before the @: marla');
  });

  it('warns that two licensed accounts are two paid seats, and says nothing of the kind otherwise', async () => {
    api.duplicates.mockResolvedValue({ items: [pair({ both_licensed: true, a: person('m@a.com', { licensed: true }), b: person('mf@b.com', { licensed: true }) })], total: 1 });
    show();
    expect(await screen.findByText(/two paid seats/)).toBeInTheDocument();
    expect(screen.getAllByText(/· licensed/)).toHaveLength(2);
  });

  it('says so when there are none, and when it could not look', async () => {
    api.duplicates.mockResolvedValueOnce({ items: [], total: 0 });
    show();
    expect(await screen.findByText('No possible duplicates found')).toBeInTheDocument();
    expect(screen.queryByTestId('duplicate-pair')).not.toBeInTheDocument();
  });

  it('says it could not look instead of showing an empty list', async () => {
    api.duplicates.mockRejectedValue(new Error('API 500'));
    show();
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not look for duplicates: API 500');
  });

  it('merges only after a second press, with the two addresses and the client, then refreshes the list and tells the page', async () => {
    const changed = vi.fn();
    api.mergePeople.mockResolvedValue({ kind: 'merge', email: 'marla@a.com', other: 'marla@b.com' });
    show(changed);
    const card = await screen.findByTestId('duplicate-pair');
    await userEvent.click(within(card).getByRole('button', { name: 'Merge these two' }));
    expect(api.mergePeople).not.toHaveBeenCalled();
    api.duplicates.mockResolvedValue({ items: [], total: 0 });
    await userEvent.click(within(card).getByRole('button', { name: 'Yes, merge them' }));
    await waitFor(() => expect(api.mergePeople).toHaveBeenCalledWith({ client_id: 'c1', email: 'marla@a.com', with_email: 'marla@b.com' }));
    await waitFor(() => expect(changed).toHaveBeenCalledTimes(1));
    expect(await screen.findByText('No possible duplicates found')).toBeInTheDocument();
  });

  it('can be cancelled after the first press without merging anything', async () => {
    show();
    const card = await screen.findByTestId('duplicate-pair');
    await userEvent.click(within(card).getByRole('button', { name: 'Merge these two' }));
    await userEvent.click(within(card).getByRole('button', { name: 'Cancel' }));
    expect(within(card).getByRole('button', { name: 'Merge these two' })).toBeInTheDocument();
    expect(api.mergePeople).not.toHaveBeenCalled();
  });

  it('dismisses a pair as not the same person at once, remembered through the existing route', async () => {
    api.separatePeople.mockResolvedValue({ kind: 'separate', email: 'marla@b.com', other: 'marla@a.com' });
    show();
    const card = await screen.findByTestId('duplicate-pair');
    api.duplicates.mockResolvedValue({ items: [], total: 0 });
    await userEvent.click(within(card).getByRole('button', { name: 'Not the same person' }));
    await waitFor(() => expect(api.separatePeople).toHaveBeenCalledWith({ client_id: 'c1', email: 'marla@b.com', from_email: 'marla@a.com' }));
    expect(api.mergePeople).not.toHaveBeenCalled();
    expect(await screen.findByText('No possible duplicates found')).toBeInTheDocument();
  });

  it('shows why a merge failed and leaves the pair on the page', async () => {
    api.mergePeople.mockRejectedValue(new Error('A person cannot be built from more than six addresses'));
    show();
    const card = await screen.findByTestId('duplicate-pair');
    await userEvent.click(within(card).getByRole('button', { name: 'Merge these two' }));
    await userEvent.click(within(card).getByRole('button', { name: 'Yes, merge them' }));
    expect(await within(card).findByRole('alert')).toHaveTextContent('more than six addresses');
    expect(screen.getByTestId('duplicate-pair')).toBeInTheDocument();
  });
});
