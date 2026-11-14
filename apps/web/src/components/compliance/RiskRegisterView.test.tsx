import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
  create: vi.fn(),
  update: vi.fn(),
  archive: vi.fn(),
  restore: vi.fn(),
  library: vi.fn(),
  fromLibrary: vi.fn(),
  addTask: vi.fn(),
  updateTask: vi.fn(),
  deleteTask: vi.fn(),
}));
vi.mock('@/lib/api', () => ({ apiErrorDetail: (e: unknown) => (e instanceof Error ? e.message : null), riskRegisterApi: api, msspApi: { listChildren: async () => [] } }));

import { RiskRegisterView, cellLevel } from './RiskRegisterView';

const risk = (over: Record<string, unknown> = {}) => ({
  id: 'r1', ref: 'R-1', title: 'Phishing leads to a taken-over account', description: 'Details here', category: 'Email and phishing', owner: 'Hal', likelihood: 4, impact: 4,
  inherent_score: 16, inherent_level: 'critical', treatment: 'undecided', treatment_note: '', residual_likelihood: null, residual_impact: null, residual_score: null, residual_level: null,
  status: 'open', open_tasks: 0, updated_at: '2026-11-14T10:00:00Z', archived_at: null, ...over,
});
const detail = (over: Record<string, unknown> = {}) => ({ ...risk(), tasks: [], history: [{ actor: 'hal@goliveoak.com', action: 'created', detail: 'added; inherent 16', created_at: '2026-11-14T10:00:00Z' }], ...over });
const register = (risks = [risk()], over: Record<string, unknown> = {}) => ({
  risks,
  summary: { total: risks.length, by_level: { critical: risks.length, high: 0, medium: 0, low: 0 }, matrix: [[0, 0, 0, 0, 0], [0, 0, 0, 1, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]], open_tasks: 2, overdue_tasks: 1, untreated: risks.length, ...over },
  categories: ['Email and phishing', 'Other'],
});

beforeEach(() => {
  Object.values(api).forEach((m) => m.mockReset());
  api.list.mockResolvedValue(register());
  api.get.mockResolvedValue(detail());
  window.history.replaceState(null, '', '/compliance/risk-register');
});

describe('cellLevel', () => {
  it('colours a grid cell by likelihood times impact', () => {
    expect([cellLevel(1, 1), cellLevel(2, 3), cellLevel(3, 4), cellLevel(4, 4), cellLevel(5, 5)]).toEqual(['low', 'medium', 'high', 'critical', 'critical']);
  });
});

describe('RiskRegisterView', () => {
  it('opens on the dashboard: counts by level, the task line with overdue ones named, and the grid', async () => {
    render(<RiskRegisterView />);
    expect(await screen.findByTestId('risk-dashboard')).toBeTruthy();
    expect(screen.getByTestId('count-critical')).toHaveTextContent('1');
    expect(screen.getByTestId('risk-dashboard')).toHaveTextContent('1 with no treatment decided');
    expect(screen.getByTestId('risk-dashboard')).toHaveTextContent('2 open tasks (1 overdue)');
    expect(screen.getByTestId('risk-grid')).toBeTruthy();
    expect(api.list).toHaveBeenCalledWith('', false);
  });

  it('lists the risks in the Register tab with their score, and opens one with its history', async () => {
    render(<RiskRegisterView />);
    await userEvent.click(await screen.findByRole('tab', { name: 'register' }));
    const table = await screen.findByTestId('risk-table');
    expect(within(table).getByText('Phishing leads to a taken-over account')).toBeTruthy();
    expect(within(table).getByText('16')).toBeTruthy();
    await userEvent.click(within(table).getByRole('button', { name: 'Phishing leads to a taken-over account' }));
    expect(api.get).toHaveBeenCalledWith('', 'r1');
    expect(await screen.findByTestId('risk-detail')).toHaveTextContent('Details here');
    expect(screen.getByTestId('risk-history')).toHaveTextContent('added; inherent 16');
  });

  it('adds a risk from the form and opens it', async () => {
    api.create.mockResolvedValue(detail({ id: 'r2', ref: 'R-2', title: 'Lost laptop' }));
    render(<RiskRegisterView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Add risk' }));
    await userEvent.type(await screen.findByLabelText('Risk title'), 'Lost laptop');
    await userEvent.click(screen.getByRole('button', { name: 'Save risk' }));
    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    expect(api.create.mock.calls[0][1]).toMatchObject({ title: 'Lost laptop', likelihood: 3, impact: 3, category: 'Other', owner: null });
    expect((await screen.findByTestId('risk-detail')).textContent).toContain('Lost laptop');
  });

  it('sets the treatment from the open risk, and a residual rating takes both values', async () => {
    api.update.mockImplementation(async (_c: string, _id: string, body: Record<string, unknown>) => detail({ ...body, treatment: (body.treatment as string) ?? 'undecided' }));
    render(<RiskRegisterView />);
    await userEvent.click(await screen.findByRole('tab', { name: 'register' }));
    await userEvent.click(within(await screen.findByTestId('risk-table')).getByRole('button', { name: /Phishing/ }));
    await userEvent.selectOptions(await screen.findByLabelText('Treatment'), 'mitigate');
    await waitFor(() => expect(api.update).toHaveBeenCalledWith('', 'r1', { treatment: 'mitigate' }));
    await userEvent.selectOptions(screen.getByLabelText('Residual likelihood'), '2');
    await waitFor(() => expect(api.update).toHaveBeenLastCalledWith('', 'r1', { residual_likelihood: 2, residual_impact: 2 }));
  });

  it('adds a task, ticks one off, and says which is overdue', async () => {
    api.addTask.mockResolvedValue(detail({ tasks: [{ id: 't1', title: 'Turn on MFA', owner: null, due_date: '2026-11-01', done: false, done_at: null, overdue: true }], open_tasks: 1 }));
    api.updateTask.mockResolvedValue(detail({ tasks: [{ id: 't1', title: 'Turn on MFA', owner: null, due_date: '2026-11-01', done: true, done_at: '2026-11-14T10:00:00Z', overdue: false }] }));
    render(<RiskRegisterView />);
    await userEvent.click(await screen.findByRole('tab', { name: 'register' }));
    await userEvent.click(within(await screen.findByTestId('risk-table')).getByRole('button', { name: /Phishing/ }));
    await userEvent.type(await screen.findByLabelText('New task'), 'Turn on MFA');
    await userEvent.click(screen.getByRole('button', { name: 'Add task' }));
    await waitFor(() => expect(api.addTask).toHaveBeenCalledWith('', 'r1', { title: 'Turn on MFA', owner: null, due_date: null }));
    expect(await screen.findByText('overdue')).toBeTruthy();
    await userEvent.click(screen.getByLabelText('Done: Turn on MFA'));
    await waitFor(() => expect(api.updateTask).toHaveBeenCalledWith('', 'r1', 't1', { done: true }));
    await waitFor(() => expect(screen.queryByText('overdue')).toBeNull());
  });

  it('archives a risk and an archived one offers Restore, with the archive tab asking for archived risks', async () => {
    api.archive.mockResolvedValue(detail({ status: 'archived', archived_at: '2026-11-14T11:00:00Z' }));
    render(<RiskRegisterView />);
    await userEvent.click(await screen.findByRole('tab', { name: 'register' }));
    await userEvent.click(within(await screen.findByTestId('risk-table')).getByRole('button', { name: /Phishing/ }));
    await userEvent.click(await screen.findByRole('button', { name: 'Archive risk' }));
    await waitFor(() => expect(api.archive).toHaveBeenCalledWith('', 'r1'));
    expect(await screen.findByRole('button', { name: 'Restore risk' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Edit risk' })).toBeNull();
    api.list.mockResolvedValue(register([]));
    await userEvent.click(screen.getByRole('tab', { name: 'archive' }));
    await waitFor(() => expect(api.list).toHaveBeenLastCalledWith('', true));
    expect(await screen.findByTestId('risk-empty')).toHaveTextContent('No archived risks.');
  });

  it('adds a common risk from the library once, and the button then says Added', async () => {
    api.library.mockResolvedValue([{ id: 'ransomware', title: 'Ransomware encrypts the file servers', category: 'Endpoints and devices', likelihood: 3, impact: 5, description: 'Files are locked.', added: false }]);
    api.fromLibrary.mockResolvedValue(detail({ id: 'r3', title: 'Ransomware encrypts the file servers' }));
    render(<RiskRegisterView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Common risks' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Add: Ransomware encrypts the file servers' }));
    await waitFor(() => expect(api.fromLibrary).toHaveBeenCalledWith('', 'ransomware'));
    expect(await screen.findByRole('button', { name: 'Added: Ransomware encrypts the file servers' })).toBeDisabled();
  });

  it('reads the client from the address and shows the reason when the API refuses', async () => {
    window.history.replaceState(null, '', '/compliance/risk-register?client=c9');
    api.list.mockRejectedValue(new Error('Client not found'));
    render(<RiskRegisterView />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Client not found');
    await waitFor(() => expect(api.list).toHaveBeenCalledWith('c9', false));
  });
});
