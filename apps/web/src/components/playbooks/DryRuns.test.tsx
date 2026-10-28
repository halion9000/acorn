import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { SWRConfig } from 'swr';
import type { PlaybookDryRun } from '@/lib/api';

const api = vi.hoisted(() => ({ list: vi.fn() }));
vi.mock('@/lib/api', () => ({ playbookDryRunsApi: api }));
vi.mock('next/link', () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));

import { AlertDryRunsSection, DryRunsTab, stepsLine } from './DryRuns';

const run = (over: Partial<PlaybookDryRun> = {}): PlaybookDryRun => ({
  alert_id: 'a1',
  alert_title: 'Sign-in succeeded after 7 wrong passwords - jhanus@blanco.gov',
  client_id: 'c1',
  client_name: 'Blanco County',
  playbook_id: 'ato-mfa-v1',
  playbook_name: 'ATO: Credential stuffing',
  matched_on: ['severity high', 'tag account-takeover'],
  steps: [
    { id: 'e1', type: 'enrich', name: '' },
    { id: 'r1', type: 'revoke_session', name: '' },
  ],
  created_at: '2026-10-28T12:00:00Z',
  ...over,
});

const wrap = (ui: React.ReactNode) => render(<SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>{ui}</SWRConfig>);

beforeEach(() => {
  api.list.mockReset();
});

describe('stepsLine', () => {
  it('lists the step types in order with spaces for underscores', () => {
    expect(stepsLine(run().steps)).toBe('enrich → revoke session');
    expect(stepsLine([])).toBe('');
  });
});

describe('the section on an alert', () => {
  it('lists the playbooks that would have run, why, and the steps, and says nothing was run', async () => {
    api.list.mockResolvedValue({ nothing_was_run: true, items: [run()] });
    wrap(<AlertDryRunsSection alertId="a1" />);
    const section = await screen.findByRole('region', { name: 'Playbooks that would have run' });
    expect(api.list).toHaveBeenCalledWith({ alertId: 'a1', limit: 20 });
    expect(within(section).getByText('Nothing was run. This shows what the playbook would have done.')).toBeInTheDocument();
    expect(within(section).getByText('ATO: Credential stuffing')).toBeInTheDocument();
    expect(within(section).getByText('Matched on: severity high, tag account-takeover')).toBeInTheDocument();
    expect(within(section).getByTestId('dry-run-steps')).toHaveTextContent('enrich → revoke session');
  });

  it('renders nothing for an alert no playbook would have run for', async () => {
    api.list.mockResolvedValue({ nothing_was_run: true, items: [] });
    const view = wrap(<AlertDryRunsSection alertId="a1" />);
    await vi.waitFor(() => expect(api.list).toHaveBeenCalled());
    expect(view.container).toBeEmptyDOMElement();
  });

  it('renders nothing, and does not break the alert, when the list cannot be read', async () => {
    api.list.mockImplementation(() => Promise.reject(new Error('403')));
    const view = wrap(<AlertDryRunsSection alertId="a2" />);
    await vi.waitFor(() => expect(api.list).toHaveBeenCalled());
    expect(view.container).toBeEmptyDOMElement();
  });
});

describe('the Playbooks page tab', () => {
  it('lists recent dry runs with the client and a link to the alert, and explains how this is switched on', async () => {
    api.list.mockResolvedValue({ nothing_was_run: true, items: [run(), run({ alert_id: 'a2', alert_title: 'Device code sign-in', playbook_id: 'p2', playbook_name: 'ATO: Session theft' })] });
    wrap(<DryRunsTab />);
    const rows = await screen.findAllByTestId('dry-run');
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByRole('link')).toHaveAttribute('href', '/alerts/a1');
    expect(rows[0]).toHaveTextContent('Blanco County');
    expect(screen.getByText(/Automated playbooks/)).toBeInTheDocument();
    expect(api.list).toHaveBeenCalledWith({ limit: 100 });
  });

  it('says there are none yet and when they appear', async () => {
    api.list.mockResolvedValue({ nothing_was_run: true, items: [] });
    wrap(<DryRunsTab />);
    expect(await screen.findByTestId('no-dry-runs')).toHaveTextContent('No dry runs yet');
  });

  it('says so when they cannot be loaded', async () => {
    api.list.mockImplementation(() => Promise.reject(new Error('500')));
    wrap(<DryRunsTab />);
    expect(await screen.findByText("Couldn't load the dry runs.")).toBeInTheDocument();
  });
});
