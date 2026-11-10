import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ caps: [] as string[], fresh: null as string[] | null, becCases: vi.fn(), startBec: vi.fn(), becCase: vi.fn() }));
vi.mock('@/lib/api', () => ({
  authApi: { currentUser: () => ({ capabilities: api.caps }), freshCapabilities: () => (api.fresh ? Promise.resolve(api.fresh) : Promise.reject(new Error('down'))) },
  identitiesApi: { becCases: api.becCases, startBec: api.startBec, becCase: api.becCase },
}));

import { BecSearch, Section, canOfferBec, maybeParse, scoreOf, sectionTitle, shortenedNote } from './BecSearch';

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
  it("shows CIPP's own rating and the checks that could not finish beside a finished search, and invents nothing when CIPP gave none", async () => {
    api.becCases.mockResolvedValue({
      items: [
        item({ id: 'h', case_ref: 'BEC-H', status: 'done', summary: { level: 'High', score: 9, incomplete: ['SignIns', 'MobileDevices'] } }),
        item({ id: 'l', case_ref: 'BEC-L', status: 'done', summary: { level: 'Low', score: 1 } }),
        item({ id: 'n', case_ref: 'BEC-N', status: 'done', summary: {} }),
      ],
    });
    show();
    expect(await screen.findByText('CIPP rates it High (score 9)')).toBeInTheDocument();
    expect(screen.getByText('2 checks could not finish: SignIns, MobileDevices')).toBeInTheDocument();
    expect(screen.getByText('CIPP rates it Low (score 1)')).toBeInTheDocument();
    expect(screen.getAllByText(/CIPP rates it/)).toHaveLength(2);
    expect(screen.queryByText(/clean|safe|compromised/i)).toBeNull();
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

describe('the note about shortened lists', () => {
  it('says which lists were cut and how many were kept, and nothing when none were', () => {
    expect(shortenedNote({ shortened: [{ path: 'SignIns', kept: 100, total: 3000 }] })).toBe('Some long lists were shortened to keep the report (SignIns: first 100 of 3,000). The rest is unchanged.');
    expect(shortenedNote({ shortened: [] })).toBeNull();
    expect(shortenedNote({ level: 'High' })).toBeNull();
    expect(shortenedNote(null)).toBeNull();
  });

  it('names at most six and counts the rest, and ignores entries that are not lists of numbers', () => {
    const many = Array.from({ length: 9 }, (_, i) => ({ path: `L${i}`, kept: 10, total: 20 + i }));
    const note = shortenedNote({ shortened: [...many, { path: 7 }, 'junk'] })!;
    expect(note).toContain('L5: first 10 of 25');
    expect(note).not.toContain('L6:');
    expect(note).toContain('and 5 more');
  });
});

describe('the score in the report', () => {
  const breakdown = JSON.stringify([
    { Count: 10, Signal: 'NewRules', Weight: 1, Applied: true, Description: 'Inbox rules exist on the mailbox' },
    { Count: 0, Signal: 'SuspiciousRules', Weight: 4, Applied: false, Description: 'An inbox rule forwards externally' },
    { Count: 16, Signal: 'ForeignActivity', Weight: 3, Applied: true, Description: 'Rule, safelist, sharing or mail activity from outside the usage location' },
  ]);
  const report = { Score: { Level: 'High', Value: 29, Breakdown: breakdown }, MailboxRules: [] };

  it('reads the breakdown CIPP sends as JSON text, split into the signals that fired and the ones that found nothing', () => {
    expect(maybeParse('[{"a":1}]')).toEqual([{ a: 1 }]);
    expect(maybeParse('not json [')).toBe('not json [');
    expect(maybeParse(5)).toBe(5);
    const score = scoreOf(report);
    expect(score?.level).toBe('High');
    expect(score?.value).toBe(29);
    expect(score?.fired.map((s) => s.signal)).toEqual(['NewRules', 'ForeignActivity']);
    expect(score?.quiet.map((s) => s.signal)).toEqual(['SuspiciousRules']);
    expect(scoreOf({})).toBeNull();
    expect(scoreOf({ Score: 3 })).toBeNull();
  });

  it('shows a summary above the sections: the score, a row for each signal that fired with its plain description, and the quiet ones folded away', async () => {
    api.becCases.mockResolvedValue({ items: [item({ status: 'done' })] });
    api.becCase.mockResolvedValue({ ...item({ status: 'done' }), report });
    show();
    await userEvent.setup().click(await screen.findByRole('button', { name: 'View report' }));
    const summary = await screen.findByTestId('bec-score-summary');
    expect(summary).toHaveTextContent('CIPP score: High (29)');
    expect(summary).toHaveTextContent('2 signals fired');
    expect(screen.getByTestId('signal-ForeignActivity')).toHaveTextContent('Rule, safelist, sharing or mail activity from outside the usage location');
    expect(screen.getByTestId('signal-ForeignActivity')).toHaveTextContent('16');
    expect(summary).toHaveTextContent('Checked and found nothing (1)');
    expect(screen.queryByText(/Breakdown.*\[\{/)).toBeNull();
  });
});

