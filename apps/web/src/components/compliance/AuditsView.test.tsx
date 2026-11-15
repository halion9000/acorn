import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ list: vi.fn(), get: vi.fn(), start: vi.fn(), patch: vi.fn(), addRequest: vi.fn(), fromControls: vi.fn(), patchRequest: vi.fn() }));
const csv = vi.hoisted(() => vi.fn());
const save = vi.hoisted(() => vi.fn());
vi.mock('@/lib/saveFile', () => ({ saveText: save }));
vi.mock('@/lib/api', () => ({
  downloadCsv: csv, apiErrorDetail: (e: unknown) => (e instanceof Error ? e.message : null), auditsApi: api, msspApi: { listChildren: async () => [] } }));

import { AuditsView } from './AuditsView';

const audit = (over: Record<string, unknown> = {}) => ({
  id: 'a1', name: 'SOC 2 Type II 2026', framework: 'SOC2', auditor: 'Prescient', period_start: null, period_end: null, status: 'planning', requests: 2, open: 1, provided: 1, accepted: 0, overdue: 1, created_at: '2026-11-14T10:00:00Z', ...over,
});
const request = (over: Record<string, unknown> = {}) => ({ id: 'r1', title: 'Org chart', control_id: null, owner: 'Dana', due_date: '2026-11-01', status: 'open', overdue: true, note: '', link: null, updated_at: '2026-11-14T10:00:00Z', ...over });
const detail = (over: Record<string, unknown> = {}) => ({ ...audit(), items: [request(), request({ id: 'r2', title: 'Backup test', status: 'provided', overdue: false, link: 'https://x.example/f' })], ...over });

beforeEach(() => {
  csv.mockReset();
  save.mockReset();
  csv.mockResolvedValue('a,b\n1,2\n');
  Object.values(api).forEach((m) => m.mockReset());
  api.list.mockResolvedValue({ audits: [audit()], frameworks: ['SOC2', 'ISO27001'] });
  api.get.mockResolvedValue(detail());
  window.history.replaceState(null, '', '/compliance/audits');
});

describe('AuditsView', () => {
  it('lists the audits with how many requests are accepted and how many are overdue', async () => {
    render(<AuditsView />);
    const row = await screen.findByTestId('audit-row');
    expect(row).toHaveTextContent('SOC 2 Type II 2026');
    expect(row).toHaveTextContent('0 of 2 accepted, 1 overdue');
  });

  it('opens an audit, answers a request step by step, adds one, adds the ones the controls need, and moves the stage', async () => {
    api.patchRequest.mockResolvedValue(detail());
    api.addRequest.mockResolvedValue(detail());
    api.fromControls.mockResolvedValue(detail());
    api.patch.mockResolvedValue(detail({ status: 'fieldwork' }));
    render(<AuditsView />);
    await userEvent.click(await screen.findByRole('button', { name: 'SOC 2 Type II 2026' }));
    const box = await screen.findByTestId('audit-detail');
    expect(screen.getByTestId('audit-progress')).toHaveTextContent('2 requests: 1 open (1 overdue), 1 provided, 0 accepted.');
    await userEvent.click(within(box).getByRole('button', { name: 'Mark Org chart provided' }));
    await waitFor(() => expect(api.patchRequest).toHaveBeenCalledWith('', 'a1', 'r1', { status: 'provided' }));
    await userEvent.click(within(box).getByRole('button', { name: 'Accept Backup test' }));
    await waitFor(() => expect(api.patchRequest).toHaveBeenCalledWith('', 'a1', 'r2', { status: 'accepted' }));
    await userEvent.type(within(box).getByLabelText('Request'), 'Pen test report');
    await userEvent.click(within(box).getByRole('button', { name: 'Add request' }));
    await waitFor(() => expect(api.addRequest).toHaveBeenCalledWith('', 'a1', { title: 'Pen test report', owner: null, due_date: null }));
    await userEvent.click(within(box).getByRole('button', { name: 'Add requests for the controls that need evidence' }));
    await waitFor(() => expect(api.fromControls).toHaveBeenCalledWith('', 'a1'));
    await userEvent.click(within(box).getByRole('button', { name: 'Move to fieldwork' }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('', 'a1', { status: 'fieldwork' }));
  });

  it('shows the reason when the audit cannot be completed, and a complete audit has no buttons to change it', async () => {
    api.patch.mockRejectedValue(new Error('1 request is still open.'));
    api.get.mockResolvedValue(detail({ status: 'review' }));
    render(<AuditsView />);
    await userEvent.click(await screen.findByRole('button', { name: 'SOC 2 Type II 2026' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Move to complete' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('1 request is still open.');
    api.get.mockResolvedValue(detail({ status: 'complete' }));
    await userEvent.click(screen.getByRole('button', { name: 'Close' }));
    await userEvent.click(await screen.findByRole('button', { name: 'SOC 2 Type II 2026' }));
    const box = await screen.findByTestId('audit-detail');
    expect(within(box).queryByRole('button', { name: /^Move to/ })).toBeNull();
    expect(within(box).queryByRole('button', { name: 'Add request' })).toBeNull();
  });

  it('starts an audit', async () => {
    api.start.mockResolvedValue(detail());
    render(<AuditsView />);
    await screen.findByTestId('audit-row');
    await userEvent.click(screen.getByRole('button', { name: 'Start an audit' }));
    await userEvent.type(screen.getByLabelText('Name of the audit'), 'ISO 2026');
    await userEvent.selectOptions(screen.getByLabelText('Framework'), 'ISO27001');
    await userEvent.click(screen.getByRole('button', { name: 'Start' }));
    await waitFor(() => expect(api.start).toHaveBeenCalledWith('', { name: 'ISO 2026', framework: 'ISO27001', auditor: null }));
  });

  it('says so when there are no audits, and shows the reason when they cannot be loaded', async () => {
    api.list.mockResolvedValue({ audits: [], frameworks: ['SOC2'] });
    const { unmount } = render(<AuditsView />);
    expect(await screen.findByTestId('audits-empty')).toBeTruthy();
    unmount();
    api.list.mockRejectedValue(new Error('Forbidden'));
    render(<AuditsView />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Forbidden');
  });
});

describe('AuditsView export', () => {
  it('Export CSV fetches the file from the server and hands it to the browser as audits.csv', async () => {
    render(<AuditsView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Export CSV' }));
    await waitFor(() => expect(save).toHaveBeenCalledWith('audits.csv', 'a,b\n1,2\n'));
    expect(csv.mock.calls[0]![0]).toBe('/api/v1/compliance/audits/export.csv');
  });

  it('says why when the export is refused', async () => {
    csv.mockRejectedValue(new Error('Forbidden'));
    render(<AuditsView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Export CSV' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Forbidden');
    expect(save).not.toHaveBeenCalled();
  });
});
