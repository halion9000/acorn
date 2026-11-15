import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ list: vi.fn(), record: vi.fn() }));
vi.mock('@/lib/api', () => ({ apiErrorDetail: (e: unknown) => (e instanceof Error ? e.message : null), controlTestsApi: api, msspApi: { listChildren: async () => [] } }));

import { ControlTestsView } from './ControlTestsView';

const result = (over: Record<string, unknown> = {}) => ({
  id: 'malware', title: 'Machines are protected against malware', why: 'Endpoint protection is installed and reporting.', state: 'pass', met: 1, total: 1,
  checks: [{ key: 'huntress_protection', status: 'met' }], controls: [{ framework: 'SOC2', control_id: 'CC6.8', on: true }, { framework: 'HIPAA', control_id: '164.308(a)(5)(ii)(B)', on: false }], ...over,
});
const tests = (results = [result(), result({ id: 'mfa', title: 'Multi-factor sign-in is required', state: 'fail', met: 0, total: 1, checks: [{ key: 'liongard_m365_weak_mfa', status: 'not_met' }] }), result({ id: 'backups', title: 'Data is backed up', state: 'not_tested', met: 0, total: 0, checks: [] })], over: Record<string, unknown> = {}) => ({
  results, counts: { pass: 1, fail: 1, partly: 0, not_tested: 1 }, enabled: ['SOC2'], checks_held: 4, ...over,
});

beforeEach(() => {
  api.list.mockReset();
  api.record.mockReset();
  api.list.mockResolvedValue(tests());
  window.history.replaceState(null, '', '/compliance/tests');
});

describe('ControlTestsView', () => {
  it('lists each test with its result, the checks it looked at and the controls it answers, marking a framework that is not on', async () => {
    render(<ControlTestsView />);
    const mfa = await screen.findByTestId('test-mfa');
    expect(mfa).toHaveTextContent('Failing: 0 of 1 checks met');
    expect(mfa).toHaveTextContent('liongard m365 weak mfa: not met');
    const malware = screen.getByTestId('test-malware');
    expect(malware).toHaveTextContent('Passing: 1 of 1 checks met');
    expect(malware).toHaveTextContent('SOC2 CC6.8, HIPAA 164.308(a)(5)(ii)(B) (not on)');
    expect(screen.getByTestId('test-backups')).toHaveTextContent('Not tested');
    expect(screen.getByRole('tab', { name: 'Failing (1)' })).toBeTruthy();
  });

  it('a tab narrows the list to one result', async () => {
    render(<ControlTestsView />);
    await screen.findByTestId('tests-list');
    await userEvent.click(screen.getByRole('tab', { name: 'Failing (1)' }));
    const list = screen.getByTestId('tests-list');
    expect(within(list).getAllByRole('listitem')).toHaveLength(1);
    expect(within(list).getByTestId('test-mfa')).toBeTruthy();
  });

  it('records the results as evidence and says how many pieces were written and replaced', async () => {
    api.record.mockResolvedValue({ written: 3, replaced: 2, results: tests() });
    render(<ControlTestsView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Record as evidence' }));
    await waitFor(() => expect(api.record).toHaveBeenCalledWith(''));
    expect(await screen.findByTestId('tests-note')).toHaveTextContent('Recorded 3 pieces of evidence (replacing 2 from the last time).');
  });

  it('says so when there was nothing to record, when no checks have been read, and when no framework is on', async () => {
    api.list.mockResolvedValue(tests([result({ state: 'not_tested', met: 0, total: 0, checks: [] })], { checks_held: 0, enabled: [] }));
    api.record.mockResolvedValue({ written: 0, replaced: 0, results: tests([], { checks_held: 0, enabled: [] }) });
    render(<ControlTestsView />);
    expect(await screen.findByTestId('tests-no-checks')).toBeTruthy();
    expect(screen.getByText(/No framework is turned on/)).toBeTruthy();
    await userEvent.click(screen.getByRole('button', { name: 'Record as evidence' }));
    expect(await screen.findByTestId('tests-note')).toHaveTextContent('Nothing to record');
  });

  it('shows the reason when the tests cannot be loaded', async () => {
    api.list.mockRejectedValue(new Error('Forbidden'));
    render(<ControlTestsView />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Forbidden');
  });
});
