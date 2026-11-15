import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const listChildren = vi.hoisted(() => vi.fn());
const enabledMock = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api', () => ({ msspApi: { listChildren }, complianceDashboardApi: { enabled: enabledMock } }));
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
  enabledMock.mockReset().mockImplementation(() => Promise.reject(new Error('not read')));
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

  it('shows no client choice for an organization with no clients', async () => {
    listChildren.mockResolvedValue([]);
    renderIndex();
    await waitFor(() => expect(listChildren).toHaveBeenCalled());
    expect(screen.queryByLabelText('Client')).toBeNull();
  });

  it('starts on the own company of the organization (a client in the list, no "My organization" line), and puts the chosen client on every card and in the address', async () => {
    listChildren.mockResolvedValue([{ id: 'c1', name: 'Acme Dental' }, { id: 'c2', name: 'Live Oak IT Partners' }, { id: 'c3', name: 'Beta Law' }]);
    renderIndex();
    const user = userEvent.setup();
    const picker = (await screen.findByLabelText('Client')) as HTMLSelectElement;
    expect(Array.from(picker.options).map((o) => o.textContent)).toEqual(['Acme Dental', 'Beta Law', 'Live Oak IT Partners']);
    await waitFor(() => expect(screen.getByRole('link', { name: /SOC 2 Type II/ }).getAttribute('href')).toBe('/compliance/soc2?client=c2'));
    expect(window.location.search).toBe('?client=c2');
    await user.selectOptions(screen.getByLabelText('Client'), 'c3');
    expect(screen.getByRole('link', { name: /SOC 2 Type II/ }).getAttribute('href')).toBe('/compliance/soc2?client=c3');
    expect(screen.getByRole('link', { name: /HIPAA Security Rule/ }).getAttribute('href')).toBe('/compliance/hipaa?client=c3');
    expect(window.location.search).toBe('?client=c3');
  });

  it('opens on the client named in its own address, so a reload or a shared link keeps the choice', async () => {
    window.history.replaceState(null, '', '/compliance?client=c1');
    listChildren.mockResolvedValue([{ id: 'c1', name: 'Acme Dental' }]);
    renderIndex();
    await waitFor(() => expect(screen.getByRole('link', { name: /SOC 2 Type II/ }).getAttribute('href')).toBe('/compliance/soc2?client=c1'));
    expect((await screen.findByLabelText('Client') as HTMLSelectElement).value).toBe('c1');
  });
});

describe('only the frameworks turned on in the Overview are listed', () => {
  it('lists the ones that are on, for the client chosen, and none of the others', async () => {
    listChildren.mockResolvedValue([]);
    enabledMock.mockResolvedValue({ enabled: ['HIPAA'], available: [] });
    renderIndex();
    expect(await screen.findByRole('link', { name: /HIPAA Security Rule/ })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /SOC 2 Type II/ })).toBeNull();
    expect(enabledMock).toHaveBeenCalledWith('');
  });

  it('says to turn some on, with a link to the Overview, when none is on', async () => {
    listChildren.mockResolvedValue([]);
    enabledMock.mockResolvedValue({ enabled: [], available: [] });
    renderIndex();
    expect(await screen.findByTestId('no-frameworks-on')).toHaveTextContent('No framework is turned on yet');
    expect(screen.getByRole('link', { name: 'Overview' })).toHaveAttribute('href', '/compliance');
    expect(screen.queryByRole('link', { name: /SOC 2 Type II/ })).toBeNull();
  });

  it('asks for the client in the address, and lists every framework when the list could not be read', async () => {
    window.history.replaceState(null, '', '/compliance/frameworks?client=c5');
    listChildren.mockResolvedValue([{ id: 'c5', name: 'Acme Dental' }]);
    renderIndex();
    await waitFor(() => expect(enabledMock).toHaveBeenCalledWith('c5'));
    expect(await screen.findByRole('link', { name: /SOC 2 Type II/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /HIPAA Security Rule/ })).toBeInTheDocument();
  });
});

describe('how far along each framework is', () => {
  it('completion is the controls with accepted evidence over all the controls, rounded, or null when there are none', () => {
    expect(completion({ controls_covered: ['a', 'b'], controls_missing: ['c', 'd', 'e', 'f'] })).toEqual({ pct: 33, covered: 2, total: 6 });
    expect(completion({ controls_covered: [], controls_missing: ['a'] })).toEqual({ pct: 0, covered: 0, total: 1 });
    expect(completion({ controls_covered: [], controls_missing: [] })).toBeNull();
    expect(completion(undefined)).toBeNull();
  });

  it('counts the controls whose evidence is past a year, and says nothing when there are none or the API is older', () => {
    expect(completion({ controls_covered: ['a', 'b'], controls_missing: [], controls_stale: ['a'] })?.stale).toBe(1);
    expect(completion({ controls_covered: ['a'], controls_missing: [], controls_stale: [] })).not.toHaveProperty('stale');
    expect(completion({ controls_covered: ['a'], controls_missing: [] })).not.toHaveProperty('stale');
  });

  it('a card says how many controls have evidence more than a year old, and no such line when none do', async () => {
    listChildren.mockResolvedValue([]);
    authFetch.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve([
          { framework: 'SOC2', controls_covered: ['CC1', 'CC2', 'CC3'], controls_missing: ['CC4'], controls_stale: ['CC1', 'CC2'] },
          { framework: 'ISO27001', controls_covered: ['A.5.1'], controls_missing: [], controls_stale: [] },
        ]),
    });
    renderIndex();
    expect(await screen.findByTestId('framework-stale')).toHaveTextContent('2 controls have evidence more than a year old');
    expect(screen.getAllByTestId('framework-stale')).toHaveLength(1);
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
