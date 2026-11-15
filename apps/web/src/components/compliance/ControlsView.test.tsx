import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ list: vi.fn() }));
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
