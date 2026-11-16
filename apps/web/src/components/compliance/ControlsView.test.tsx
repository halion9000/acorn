import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ list: vi.fn(), setOwner: vi.fn(), addEvidence: vi.fn() }));
const csv = vi.hoisted(() => vi.fn());
const save = vi.hoisted(() => vi.fn());
vi.mock('@/lib/saveFile', () => ({ saveText: save }));
vi.mock('@/lib/api', () => ({
  downloadCsv: csv, apiErrorDetail: (e: unknown) => (e instanceof Error ? e.message : null), controlsApi: api, msspApi: { listChildren: async () => [] } }));
vi.mock('next/link', () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));

import { ControlsView } from './ControlsView';

const row = (over: Record<string, unknown> = {}) => ({
  framework: 'SOC2', control_id: 'CC1.1', title: 'Integrity and ethical values', group: 'Control environment', state: 'healthy', accepted: 2, pending: 0, rejected: 0,
  newest_evidence: '2026-11-01T00:00:00Z', age_days: 13, link: '/compliance/soc2', ...over,
});
const list = (rows = [row()], over: Record<string, unknown> = {}) => ({
  enabled: ['SOC2'], frameworks: ['SOC2'], counts: { healthy: 1, at_risk: 0, unhealthy: 0, not_tested: 0 }, total: rows.length, rows, ...over,
});

beforeEach(() => {
  csv.mockReset();
  save.mockReset();
  csv.mockResolvedValue('a,b\n1,2\n');
  api.list.mockReset();
  api.setOwner.mockReset();
  api.addEvidence.mockReset();
  api.addEvidence.mockResolvedValue({ id: 'e1', status: 'pending' });
  api.setOwner.mockResolvedValue({});
  api.list.mockResolvedValue(list());
  window.history.replaceState(null, '', '/compliance/controls');
});

describe('ControlsView', () => {
  it('lists each control with its health and evidence, linking to the framework that holds it', async () => {
    api.list.mockResolvedValue(list([row({ state: 'unhealthy', rejected: 1, control_id: 'CC1.2', title: 'Board oversight' }), row()], { counts: { healthy: 1, at_risk: 0, unhealthy: 1, not_tested: 0 } }));
    render(<ControlsView />);
    const rows = await screen.findAllByTestId('control-row');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('CC1.2');
    expect(rows[0]).toHaveTextContent('Unhealthy');
    expect(rows[1]).toHaveTextContent('2 accepted, 0 pending, 0 rejected; newest 13 days old');
    expect(within(rows[1]!).getByRole('link', { name: 'CC1.1' })).toHaveAttribute('href', '/compliance/soc2');
    expect(screen.getByRole('tab', { name: 'Unhealthy (1)' })).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'All (2)' })).toBeTruthy();
  });

  it('a tab, the framework choice and the search each ask the server for just that, and the client in the address is kept on the links', async () => {
    window.history.replaceState(null, '', '/compliance/controls?client=c9');
    render(<ControlsView />);
    await waitFor(() => expect(api.list).toHaveBeenCalledWith('c9', { framework: '', state: '', q: '' }));
    expect(within(await screen.findByTestId('control-row')).getByRole('link', { name: 'CC1.1' })).toHaveAttribute('href', '/compliance/soc2?client=c9');
    await userEvent.click(screen.getByRole('tab', { name: 'At risk (0)' }));
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith('c9', { framework: '', state: 'at_risk', q: '' }));
    await userEvent.selectOptions(screen.getByLabelText('Framework'), 'HIPAA');
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith('c9', { framework: 'HIPAA', state: 'at_risk', q: '' }));
    await userEvent.type(screen.getByLabelText('Search controls'), 'access');
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith('c9', { framework: 'HIPAA', state: 'at_risk', q: 'access' }));
  });

  it('says to turn a framework on when none is, says when nothing matches, and says when the list was cut', async () => {
    api.list.mockResolvedValue(list([], { enabled: [], frameworks: [], counts: { healthy: 0, at_risk: 0, unhealthy: 0, not_tested: 0 } }));
    const { unmount } = render(<ControlsView />);
    expect(await screen.findByTestId('controls-none-on')).toBeTruthy();
    unmount();
    api.list.mockResolvedValue(list([]));
    const second = render(<ControlsView />);
    expect(await screen.findByTestId('controls-empty')).toBeTruthy();
    second.unmount();
    api.list.mockResolvedValue(list([row()], { total: 900 }));
    render(<ControlsView />);
    expect(await screen.findByTestId('controls-cut')).toHaveTextContent('Showing the first 1 of 900');
  });

  it('shows the reason when the list cannot be loaded', async () => {
    api.list.mockRejectedValue(new Error('Forbidden'));
    render(<ControlsView />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Forbidden');
  });
});

describe('ControlsView export', () => {
  it('Export CSV fetches the file from the server and hands it to the browser as controls.csv', async () => {
    render(<ControlsView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Export CSV' }));
    await waitFor(() => expect(save).toHaveBeenCalledWith('controls.csv', 'a,b\n1,2\n'));
    expect(csv.mock.calls[0]![0]).toBe('/api/v1/compliance/controls/export.csv');
  });

  it('says why when the export is refused', async () => {
    csv.mockRejectedValue(new Error('Forbidden'));
    render(<ControlsView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Export CSV' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Forbidden');
    expect(save).not.toHaveBeenCalled();
  });
});

describe('control owners', () => {
  it('shows the owner of a control, or a way to add one', async () => {
    api.list.mockResolvedValue(list([row({ owner: 'Dana Reyes' }), row({ control_id: 'CC1.2' })]));
    render(<ControlsView />);
    const rows = await screen.findAllByTestId('control-row');
    expect(rows[0]).toHaveTextContent('Dana Reyes');
    expect(rows[1]).toHaveTextContent('Add owner');
  });

  it('names an owner on Enter, saves it for that control, and reloads the list', async () => {
    render(<ControlsView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Set owner of CC1.1' }));
    await userEvent.type(screen.getByLabelText('Owner of CC1.1'), 'Lee Park{Enter}');
    await waitFor(() => expect(api.setOwner).toHaveBeenCalledWith('', 'SOC2', 'CC1.1', 'Lee Park'));
    await waitFor(() => expect(api.list.mock.calls.length).toBeGreaterThan(1));
  });

  it('saves nothing when the owner was not changed, and Escape drops the edit', async () => {
    api.list.mockResolvedValue(list([row({ owner: 'Dana Reyes' })]));
    render(<ControlsView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Set owner of CC1.1' }));
    await userEvent.type(screen.getByLabelText('Owner of CC1.1'), '{Enter}');
    expect(api.setOwner).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Set owner of CC1.1' }));
    await userEvent.type(screen.getByLabelText('Owner of CC1.1'), 'x{Escape}');
    expect(api.setOwner).not.toHaveBeenCalled();
  });

  it('clears the owner when the box is emptied', async () => {
    api.list.mockResolvedValue(list([row({ owner: 'Dana Reyes' })]));
    render(<ControlsView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Set owner of CC1.1' }));
    await userEvent.clear(screen.getByLabelText('Owner of CC1.1'));
    await userEvent.keyboard('{Enter}');
    await waitFor(() => expect(api.setOwner).toHaveBeenCalledWith('', 'SOC2', 'CC1.1', ''));
  });
});

describe('adding evidence from the Controls page', () => {
  it('opens a form under the control, saves the evidence for that control and says it waits for review', async () => {
    render(<ControlsView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Add evidence to CC1.1' }));
    await userEvent.selectOptions(screen.getByLabelText('Kind of evidence for CC1.1'), 'policy');
    await userEvent.type(screen.getByLabelText('What the evidence for CC1.1 shows'), 'Code of conduct, kept in SharePoint');
    await userEvent.click(screen.getByRole('button', { name: 'Save evidence' }));
    await waitFor(() =>
      expect(api.addEvidence).toHaveBeenCalledWith('', {
        framework: 'SOC2',
        control_id: 'CC1.1',
        control_title: 'Integrity and ethical values',
        evidence_kind: 'policy',
        summary: 'Code of conduct, kept in SharePoint',
      }),
    );
    expect(await screen.findByRole('status')).toHaveTextContent('Evidence added to CC1.1. It waits for review on the SOC2 page.');
    expect(screen.queryByTestId('add-evidence-row')).toBeNull();
  });

  it('will not save a summary that is too short, and Cancel closes the form without saving', async () => {
    render(<ControlsView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Add evidence to CC1.1' }));
    await userEvent.type(screen.getByLabelText('What the evidence for CC1.1 shows'), 'abc');
    expect((screen.getByRole('button', { name: 'Save evidence' }) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByTestId('add-evidence-row')).toBeNull();
    expect(api.addEvidence).not.toHaveBeenCalled();
  });

  it('shows the reason when the evidence is refused', async () => {
    api.addEvidence.mockRejectedValue(new Error('Evidence needs a longer summary.'));
    render(<ControlsView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Add evidence to CC1.1' }));
    await userEvent.type(screen.getByLabelText('What the evidence for CC1.1 shows'), 'long enough');
    await userEvent.click(screen.getByRole('button', { name: 'Save evidence' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Evidence needs a longer summary.');
  });
});
