import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { RunLog, durationText, failureLine, outputText, playbookChoices, runsFor } from './RunLog';
import type { PlaybookRun } from './types';

const run = (id: string, playbook: string, over: Partial<PlaybookRun> = {}): PlaybookRun => ({
  run_id: id,
  playbook_id: playbook,
  playbook_name: playbook === 'p1' ? 'Account takeover' : 'Phishing triage',
  status: 'completed',
  started_at: '2026-10-28T10:00:00Z',
  completed_at: '2026-10-28T10:00:12Z',
  steps: [{ step_id: 's1', step_name: 'Enrich', status: 'completed', started_at: '2026-10-28T10:00:00Z', completed_at: '2026-10-28T10:00:03Z' }],
  context: {},
  dry_run: false,
  ...over,
});

const RUNS = [
  run('aaaaaaaaaaaa1', 'p1', { started_at: '2026-10-28T09:00:00Z' }),
  run('bbbbbbbbbbbb2', 'p1', { status: 'failed', started_at: '2026-10-28T11:00:00Z', steps: [{ step_id: 's1', step_name: 'Revoke sessions', status: 'failed', error: 'CIPP refused the request', output: { code: 403 } }] }),
  run('cccccccccccc3', 'p2', { started_at: '2026-10-28T10:00:00Z' }),
];

describe('helpers', () => {
  it('lists the playbooks that have runs, by name, with their run and failure counts', () => {
    expect(playbookChoices(RUNS)).toEqual([
      { id: 'p1', name: 'Account takeover', runs: 2, failed: 1 },
      { id: 'p2', name: 'Phishing triage', runs: 1, failed: 0 },
    ]);
  });
  it('shows one playbook or all, newest first', () => {
    expect(runsFor(RUNS, '').map((r) => r.run_id)).toEqual(['bbbbbbbbbbbb2', 'cccccccccccc3', 'aaaaaaaaaaaa1']);
    expect(runsFor(RUNS, 'p1').map((r) => r.run_id)).toEqual(['bbbbbbbbbbbb2', 'aaaaaaaaaaaa1']);
  });
  it('words a duration, and says nothing when the run has not finished', () => {
    expect(durationText('2026-10-28T10:00:00Z', '2026-10-28T10:00:12Z')).toBe('12 s');
    expect(durationText('2026-10-28T10:00:00Z', '2026-10-28T10:03:05Z')).toBe('3 min 5 s');
    expect(durationText('2026-10-28T10:00:00Z', '2026-10-28T10:02:00Z')).toBe('2 min');
    expect(durationText('2026-10-28T10:00:00Z', undefined)).toBe('');
    expect(durationText('2026-10-28T10:05:00Z', '2026-10-28T10:00:00Z')).toBe('');
  });
  it('shortens a step output and says plainly how many runs failed', () => {
    expect(outputText({ code: 403 })).toBe('{"code":403}');
    expect(outputText('x'.repeat(400))).toHaveLength(300);
    expect(outputText(undefined)).toBe('');
    expect(failureLine({ id: 'p1', name: 'A', runs: 8, failed: 3 })).toBe('3 of 8 runs failed');
    expect(failureLine({ id: 'p1', name: 'A', runs: 1, failed: 1 })).toBe('1 of 1 run failed');
    expect(failureLine({ id: 'p1', name: 'A', runs: 4, failed: 0 })).toBe('');
    expect(failureLine(undefined)).toBe('');
  });
});

describe('RunLog', () => {
  it('shows every run, then only the picked playbook with its failures', async () => {
    const user = userEvent.setup();
    render(<RunLog runs={RUNS} />);
    expect(screen.getAllByText(/^(Account takeover|Phishing triage)$/, { selector: 'div' })).toHaveLength(3);
    expect(screen.queryByTestId('run-failures')).toBeNull();
    await user.selectOptions(screen.getByLabelText('Playbook'), 'p1');
    expect(screen.getAllByText('Account takeover', { selector: 'div' })).toHaveLength(2);
    expect(screen.queryByText('Phishing triage', { selector: 'div' })).toBeNull();
    expect(screen.getByTestId('run-failures')).toHaveTextContent('1 of 2 runs failed');
  });

  it('opens a run to show each step with its time, its error and its output, and hides them again', async () => {
    const user = userEvent.setup();
    render(<RunLog runs={RUNS} />);
    expect(screen.queryByTestId('run-steps')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Show steps of run bbbbbbbbbbbb' }));
    const steps = screen.getByTestId('run-steps');
    expect(within(steps).getByText('Revoke sessions')).toBeInTheDocument();
    expect(steps).toHaveTextContent('CIPP refused the request');
    expect(steps).toHaveTextContent('{"code":403}');
    await user.click(screen.getByRole('button', { name: 'Hide steps of run bbbbbbbbbbbb' }));
    expect(screen.queryByTestId('run-steps')).toBeNull();
  });
});
