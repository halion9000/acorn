import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const listChildren = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api', () => ({ msspApi: { listChildren } }));
const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));
vi.mock('next/link', () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));

import { FrameworkIndex, completion, frameworkHref } from './FrameworkIndex';

const frameworks = [
  { id: 'soc2', name: 'SOC 2 Type II', description: 'Trust criteria.', badge: 'Enterprise' },
  { id: 'hipaa', name: 'HIPAA Security Rule', description: 'Health data safeguards.', badge: 'Healthcare' },
];

function renderIndex() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
      <FrameworkIndex frameworks={frameworks} />
    </SWRConfig>,
  );
}

beforeEach(() => {
  authFetch.mockReset();
  authFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve([]) });
  listChildren.mockReset();
  window.history.replaceState(null, '', '/compliance');
});

describe('frameworkHref', () => {
  it('is the plain framework page without a client, and carries the client (encoded) with one', () => {
    expect(frameworkHref('soc2', '')).toBe('/compliance/soc2');
    expect(frameworkHref('soc2', 'abc-123')).toBe('/compliance/soc2?client=abc-123');
    expect(frameworkHref('hipaa', 'a b&c')).toBe('/compliance/hipaa?client=a%20b%26c');
  });
});

describe('the compliance index', () => {
  it('shows a card for each framework linking to its page', async () => {
    listChildren.mockResolvedValue([]);
    renderIndex();
    expect(screen.getByRole('link', { name: /SOC 2 Type II/ }).getAttribute('href')).toBe('/compliance/soc2');
    expect(screen.getByRole('link', { name: /HIPAA Security Rule/ }).getAttribute('href')).toBe('/compliance/hipaa');
  });

  it('shows no client choice for an organisation with no clients', async () => {
    listChildren.mockResolvedValue([]);
    renderIndex();
    await waitFor(() => expect(listChildren).toHaveBeenCalled());
    expect(screen.queryByLabelText('Client')).toBeNull();
  });

  it('puts the chosen client on every card and in the address, and goes back to the plain links when the choice is cleared', async () => {
    listChildren.mockResolvedValue([{ id: 'c1', name: 'Acme Dental' }, { id: 'c2', name: 'Beta Law' }]);
    renderIndex();
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText('Client'), 'c2');
    expect(screen.getByRole('link', { name: /SOC 2 Type II/ }).getAttribute('href')).toBe('/compliance/soc2?client=c2');
    expect(screen.getByRole('link', { name: /HIPAA Security Rule/ }).getAttribute('href')).toBe('/compliance/hipaa?client=c2');
    expect(window.location.search).toBe('?client=c2');
    await user.selectOptions(screen.getByLabelText('Client'), '');
    expect(screen.getByRole('link', { name: /SOC 2 Type II/ }).getAttribute('href')).toBe('/compliance/soc2');
    expect(window.location.search).toBe('');
  });

  it('opens on the client named in its own address, so a reload or a shared link keeps the choice', async () => {
    window.history.replaceState(null, '', '/compliance?client=c1');
    listChildren.mockResolvedValue([{ id: 'c1', name: 'Acme Dental' }]);
    renderIndex();
    await waitFor(() => expect(screen.getByRole('link', { name: /SOC 2 Type II/ }).getAttribute('href')).toBe('/compliance/soc2?client=c1'));
    expect((await screen.findByLabelText('Client') as HTMLSelectElement).value).toBe('c1');
  });
});

describe('how far along each framework is', () => {
  it('completion is the controls with accepted evidence over all the controls, rounded, or null when there are none', () => {
    expect(completion({ controls_covered: ['a', 'b'], controls_missing: ['c', 'd', 'e', 'f'] })).toEqual({ pct: 33, covered: 2, total: 6 });
    expect(completion({ controls_covered: [], controls_missing: ['a'] })).toEqual({ pct: 0, covered: 0, total: 1 });
    expect(completion({ controls_covered: [], controls_missing: [] })).toBeNull();
    expect(completion(undefined)).toBeNull();
  });

  it('shows a percentage complete bar on each card, for the framework the API names, and says when it cannot be read', async () => {
    listChildren.mockResolvedValue([]);
    authFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([{ framework: 'SOC2', controls_covered: ['CC1', 'CC2', 'CC3'], controls_missing: ['CC4'] }]),
    });
    renderIndex();
    const bar = await screen.findByRole('progressbar', { name: 'Controls with accepted evidence' });
    expect(bar).toHaveAttribute('aria-valuenow', '75');
    expect(screen.getByText('75% complete')).toBeInTheDocument();
    expect(screen.getByText('3 of 4 controls have accepted evidence')).toBeInTheDocument();
    expect(screen.getByText('Progress is not available.')).toBeInTheDocument();
    expect(authFetch).toHaveBeenCalledWith('/api/v1/compliance/report');
  });

  it('says progress is not available when the report fails', async () => {
    listChildren.mockResolvedValue([]);
    authFetch.mockResolvedValue({ ok: false, status: 500, json: () => Promise.resolve({}) });
    renderIndex();
    await waitFor(() => expect(screen.getAllByText('Progress is not available.')).toHaveLength(2));
    expect(screen.queryByRole('progressbar')).toBeNull();
  });
});
