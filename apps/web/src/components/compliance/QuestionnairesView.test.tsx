import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({
  list: vi.fn(), get: vi.fn(), start: vi.fn(), patchItem: vi.fn(), approveDrafts: vi.fn(), complete: vi.fn(), exportCsv: vi.fn(), remove: vi.fn(),
  library: vi.fn(), addLibrary: vi.fn(), patchLibrary: vi.fn(), removeLibrary: vi.fn(),
}));
vi.mock('@/lib/api', () => ({ apiErrorDetail: (e: unknown) => (e instanceof Error ? e.message : null), questionnairesApi: api, msspApi: { listChildren: async () => [] } }));

import { QuestionnairesView } from './QuestionnairesView';

const summary = (over: Record<string, unknown> = {}) => ({
  id: 'q1', name: 'Acme vendor review', customer: 'Acme Dental', due_date: '2026-12-01', status: 'open', overdue: false, questions: 2, approved: 0, drafted: 1, blank: 1,
  created_at: '2026-11-14T10:00:00Z', completed_at: null, ...over,
});
const item = (over: Record<string, unknown> = {}) => ({ id: 'i1', position: 1, question: 'Do you encrypt data at rest?', answer: 'Yes, AES-256.', source: 'library', match_score: 100, approved: false, approved_by: null, ...over });
const detail = (over: Record<string, unknown> = {}) => ({ ...summary(), items: [item(), item({ id: 'i2', position: 2, question: 'What is your address?', answer: '', source: 'none', match_score: 0 })], ...over });

beforeEach(() => {
  Object.values(api).forEach((m) => m.mockReset());
  api.list.mockResolvedValue({ questionnaires: [summary()], library_size: 3, categories: ['General', 'Data protection'] });
  api.get.mockResolvedValue(detail());
  api.library.mockResolvedValue([]);
  window.history.replaceState(null, '', '/compliance/questionnaires');
});

describe('QuestionnairesView', () => {
  it('lists the questionnaires with their progress, and the library size on its tab', async () => {
    render(<QuestionnairesView />);
    const row = await screen.findByTestId('questionnaire-row');
    expect(row).toHaveTextContent('Acme vendor review');
    expect(row).toHaveTextContent('0 of 2 approved; 1 drafted, 1 blank');
    expect(screen.getByRole('tab', { name: 'Answer library (3)' })).toBeTruthy();
  });

  it('opens a questionnaire: a library draft says where it came from and how close it was, a blank question says so, and Approve only works on an answer that is saved', async () => {
    api.patchItem.mockResolvedValue(detail({ approved: 1 }));
    render(<QuestionnairesView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Acme vendor review' }));
    const rows = await screen.findAllByTestId('item-row');
    expect(rows[0]).toHaveTextContent('Drafted from the library (100% of the words)');
    expect(rows[1]).toHaveTextContent('No answer yet');
    expect((within(rows[1]!).getByRole('button', { name: 'Approve' }) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.type(within(rows[1]!).getByLabelText('Answer to question 2'), '1 Main St');
    expect((within(rows[1]!).getByRole('button', { name: 'Approve' }) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.click(within(rows[0]!).getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(api.patchItem).toHaveBeenCalledWith('', 'q1', 'i1', { approved: true }));
    await userEvent.click(within(rows[1]!).getByRole('button', { name: 'Save answer' }));
    await waitFor(() => expect(api.patchItem).toHaveBeenCalledWith('', 'q1', 'i2', { answer: '1 Main St' }));
  });

  it('approves the close matches in one go, keeps an answer in the library, and completes only when every question is approved', async () => {
    api.approveDrafts.mockResolvedValue(detail({ approved: 1 }));
    api.patchItem.mockResolvedValue(detail());
    render(<QuestionnairesView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Acme vendor review' }));
    expect((await screen.findByRole('button', { name: 'Complete' }) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.click(screen.getByRole('button', { name: 'Approve the close matches' }));
    await waitFor(() => expect(api.approveDrafts).toHaveBeenCalledWith('', 'q1'));
    const rows = screen.getAllByTestId('item-row');
    expect((within(rows[0]!).getByRole('button', { name: 'Keep in the library' }) as HTMLButtonElement).disabled).toBe(true);
    api.get.mockResolvedValue(detail({ approved: 2, drafted: 0, blank: 0, items: [item({ approved: true, source: 'manual' }), item({ id: 'i2', position: 2, answer: 'x', source: 'manual', approved: true })] }));
    await userEvent.click(screen.getByRole('button', { name: 'Close' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Acme vendor review' }));
    await userEvent.click(within((await screen.findAllByTestId('item-row'))[0]!).getByRole('button', { name: 'Keep in the library' }));
    await waitFor(() => expect(api.patchItem).toHaveBeenCalledWith('', 'q1', 'i1', { save_to_library: true }));
  });

  it('starts a questionnaire from pasted questions', async () => {
    api.start.mockResolvedValue(detail());
    render(<QuestionnairesView />);
    await screen.findByTestId('questionnaire-row');
    await userEvent.click(screen.getByRole('button', { name: 'Start a questionnaire' }));
    await userEvent.type(screen.getByLabelText('Name of the questionnaire'), 'Birch review');
    await userEvent.type(screen.getByLabelText('Questions'), 'Do you encrypt data?');
    await userEvent.click(screen.getByRole('button', { name: 'Draft the answers' }));
    await waitFor(() => expect(api.start).toHaveBeenCalledWith('', { name: 'Birch review', due_date: null, questions: 'Do you encrypt data?' }));
  });

  it('asks the form for no customer name, and deletes a questionnaire only after a yes', async () => {
    api.remove.mockResolvedValue(undefined);
    render(<QuestionnairesView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Start a questionnaire' }));
    expect(screen.queryByLabelText('Customer')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Start a questionnaire' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Acme vendor review' }));
    const ask = vi.spyOn(window, 'confirm').mockReturnValue(false);
    await userEvent.click(await screen.findByRole('button', { name: 'Delete' }));
    expect(api.remove).not.toHaveBeenCalled();
    ask.mockReturnValue(true);
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(api.remove).toHaveBeenCalledWith('', 'q1'));
    await waitFor(() => expect(screen.queryByTestId('questionnaire-detail')).toBeNull());
    ask.mockRestore();
  });

  it('the library lists the answers, adds one, and confirms or removes one', async () => {
    api.library.mockResolvedValue([{ id: 'a1', question: 'Do you test backups?', answer: 'Quarterly.', category: 'Business continuity', last_reviewed: '2026-10-01', updated_at: '2026-10-01T00:00:00Z' }]);
    api.addLibrary.mockResolvedValue({});
    api.patchLibrary.mockResolvedValue({});
    api.removeLibrary.mockResolvedValue(undefined);
    render(<QuestionnairesView />);
    await userEvent.click(await screen.findByRole('tab', { name: 'Answer library (3)' }));
    expect(await screen.findByTestId('library-row')).toHaveTextContent('confirmed 2026-10-01');
    await userEvent.click(screen.getByRole('button', { name: 'Still true' }));
    await waitFor(() => expect(api.patchLibrary).toHaveBeenCalledWith('', 'a1', { confirm: true }));
    await userEvent.type(screen.getByLabelText('Library question'), 'Do you have a SOC 2?');
    await userEvent.type(screen.getByLabelText('Library answer'), 'Yes.');
    await userEvent.click(screen.getByRole('button', { name: 'Add to the library' }));
    await waitFor(() => expect(api.addLibrary).toHaveBeenCalledWith('', { question: 'Do you have a SOC 2?', answer: 'Yes.', category: 'General' }));
    await userEvent.click(screen.getByRole('button', { name: 'Remove Do you test backups?' }));
    await waitFor(() => expect(api.removeLibrary).toHaveBeenCalledWith('', 'a1'));
  });

  it('shows the reason when the list cannot be loaded', async () => {
    api.list.mockRejectedValue(new Error('Forbidden'));
    render(<QuestionnairesView />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Forbidden');
  });
});
