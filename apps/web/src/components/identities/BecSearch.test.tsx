import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ caps: [] as string[], fresh: null as string[] | null, becCases: vi.fn(), startBec: vi.fn(), becCase: vi.fn() }));
vi.mock('@/lib/api', () => ({
  authApi: { currentUser: () => ({ capabilities: api.caps }), freshCapabilities: () => (api.fresh ? Promise.resolve(api.fresh) : Promise.reject(new Error('down'))) },
  identitiesApi: { becCases: api.becCases, startBec: api.startBec, becCase: api.becCase },
}));

import { BecSearch, Section, canOfferBec, sectionTitle } from './BecSearch';

const item = (over: Record<string, unknown> = {}) => ({
  id: 'c1', case_ref: 'BEC-1', email: 'pat@acme.com', status: 'running', step: 2, steps_total: 15, step_label: 'Sign-ins and mobile devices', message: null, summary: {},
  created_at: new Date().toISOString(), updated_at: new Date().toISOString(), finished_at: null, ...over,
});
const show = (knownTo = ['cipp']) =>
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <BecSearch clientId="c1" email="pat@acme.com" knownTo={knownTo} />
    </SWRConfig>,
  );

beforeEach(() => {
  api.caps = ['run_bec'];
  api.fresh = null;
  api.becCases.mockReset().mockResolvedValue({ items: [] });
  api.startBec.mockReset().mockResolvedValue(item({ status: 'pending', step: 0, steps_total: 0, step_label: null }));
  api.becCase.mockReset();
});

describe('who sees it', () => {
  it('only with the permission and only for a Microsoft 365 person', () => {
    expect(canOfferBec(['run_bec'], ['cipp'])).toBe(true);
    expect(canOfferBec(['respond_identities'], ['cipp'])).toBe(false);
    expect(canOfferBec(['run_bec'], ['huntress'])).toBe(false);
    expect(canOfferBec(undefined, ['cipp'])).toBe(false);
  });
  it('shows nothing without it, and asks for nothing', () => {
    api.caps = [];
    const { container } = show();
    expect(container.textContent).toBe('');
    expect(api.becCases).not.toHaveBeenCalled();
  });
  it('trusts the server over the copy kept at sign-in', async () => {
    api.caps = [];
    api.fresh = ['run_bec'];
    show();
    expect(await screen.findByRole('button', { name: 'Run BEC search' })).toBeInTheDocument();
  });
});

describe('running a search', () => {
  it('asks first and starts nothing until Yes', async () => {
    show();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Run BEC search' }));
    expect(screen.getByRole('dialog', { name: 'Run a BEC search?' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'No, cancel' }));
    expect(api.startBec).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Run BEC search' }));
    await user.click(screen.getByRole('button', { name: 'Yes, run it' }));
    await waitFor(() => expect(api.startBec).toHaveBeenCalledWith({ client_id: 'c1', email: 'pat@acme.com', confirm: true }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });
  it('shows the refusal in the window', async () => {
    api.startBec.mockRejectedValue(new Error('A search for this person is already running.'));
    show();
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Run BEC search' }));
    await user.click(screen.getByRole('button', { name: 'Yes, run it' }));
    expect(await screen.findByText('A search for this person is already running.')).toBeInTheDocument();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });
});

describe('following a search', () => {
  it('shows the step it is on while running, the reason when it failed, and a report link only when finished', async () => {
    api.becCases.mockResolvedValue({
      items: [item({ id: 'a', case_ref: 'BEC-A' }), item({ id: 'b', case_ref: 'BEC-B', status: 'failed', message: 'CIPP returned 403: the readonly role lacks the permission' }), item({ id: 'c', case_ref: 'BEC-C', status: 'done' })],
    });
    show();
    const list = await screen.findByTestId('bec-case-list');
    expect(list.textContent).toContain('Step 2 of 15: Sign-ins and mobile devices');
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '2');
    expect(list.textContent).toContain('CIPP returned 403');
    expect(screen.getAllByRole('button', { name: 'View report' })).toHaveLength(1);
  });
  it('opens the report as CIPP returned it and says a missing section is not a pass', async () => {
    api.becCases.mockResolvedValue({ items: [item({ status: 'done' })] });
    api.becCase.mockResolvedValue({ ...item({ status: 'done' }), report: { MailboxRules: [], PermissionChanges: [{ Operation: 'Add-MailboxPermission', User: 'x' }], Score: 3 } });
    show();
    await userEvent.setup().click(await screen.findByRole('button', { name: 'View report' }));
    expect(await screen.findByText('Permission Changes')).toBeInTheDocument();
    expect(screen.getByText('Add-MailboxPermission')).toBeInTheDocument();
    expect(screen.getByText('Nothing found.')).toBeInTheDocument();
    expect(screen.getByText(/not a pass/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Download JSON' })).toBeInTheDocument();
  });
});

describe('the report viewer', () => {
  it('makes readable names, tables for lists of records, rows for a record, and cuts a long list with a count', () => {
    expect(sectionTitle('MailboxRules')).toBe('Mailbox Rules');
    expect(sectionTitle('foreign_sign_ins')).toBe('Foreign sign ins');
    const many = Array.from({ length: 60 }, (_, i) => ({ n: i }));
    render(<Section name="Rows" value={many} />);
    expect(screen.getByText(/Showing 50 of 60/)).toBeInTheDocument();
  });
});
