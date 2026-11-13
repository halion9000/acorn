import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ library: vi.fn(), list: vi.fn(), create: vi.fn(), get: vi.fn(), update: vi.fn(), answer: vi.fn(), autofill: vi.fn(), settings: vi.fn(), saveSettings: vi.fn(), remove: vi.fn(), assessors: vi.fn(), trends: vi.fn(), clientTrend: vi.fn() }));
const mssp = vi.hoisted(() => ({ listChildren: vi.fn() }));
const csv = vi.hoisted(() => ({ downloadCsv: vi.fn() }));
vi.mock('@/lib/api', async (original) => ({ ...(await original<typeof import('@/lib/api')>()), msspApi: mssp }));
vi.mock('@/lib/csv', async (original) => ({ ...(await original<typeof import('@/lib/csv')>()), downloadCsv: csv.downloadCsv }));
vi.mock('@/lib/vcioRisk', async (original) => ({ ...(await original<typeof import('@/lib/vcioRisk')>()), vcioRiskApi: api }));

import { ApiError } from '@/lib/api';
import { assessmentCsv, assessorChoices, autofillSentence, changeText, excludedFor, keepQuestions, losesPoints, pct, type RiskAggregate, type RiskAssessment, type RiskLibrary, type RiskQuestion, type RiskScorecard } from '@/lib/vcioRisk';
import { RiskScoringView } from './RiskScoringView';

const q = (over: Partial<RiskQuestion>): RiskQuestion => ({ id: 'ADM-001', category: 'Administrative', subsection: 'Onboarding', text: 'Is there an onboarding plan?', type: 'yesno', preferred: '', good: 'Yes', severity: 'High', csf: 'GV.RR', csf_function: 'Govern', csf_name: 'Roles', ...over });
const QUESTIONS = [
  q({}),
  q({ id: 'NET-002', category: 'Network & Infrastructure', subsection: 'Firewalls', text: 'Is RDP port 3389 exposed?', good: 'No', severity: 'Critical', csf: 'PR.AA', csf_function: 'Protect' }),
  q({ id: 'TS-001', category: 'Tech Stack', subsection: 'Network Equipment', text: 'What is the client firewall?', type: 'vendor', preferred: 'Meraki / UniFi', severity: 'Medium' }),
  q({ id: 'GW-001', category: 'Google Workspace', subsection: 'Gmail', text: 'Is DKIM signing on?', severity: 'High' }),
];
const SETTINGS = { points: { Critical: 10, High: 6, Medium: 3, Low: 1 }, partial: 0.5, unknown: 0, alternative: 1, cap_on: true, cap: 0.84, green: 0.95, amber: 0.85, weights: { Administrative: 8, 'Network & Infrastructure': 12, 'Tech Stack': 15, 'Google Workspace': 20 } };
const LIBRARY: RiskLibrary = { questions: QUESTIONS, categories: ['Administrative', 'Network & Infrastructure', 'Google Workspace', 'Tech Stack'], csf_functions: ['Govern', 'Protect', 'Respond'], severities: ['Critical', 'High', 'Medium', 'Low'], yesno_answers: ['Yes', 'No', 'Partial', 'Unknown', 'N/A'], vendor_answers: ['Preferred', 'Alternative', 'None', 'Unknown', 'N/A'], defaults: SETTINGS };
const agg = (name: string, score: number | null, over: Record<string, unknown> = {}): RiskAggregate => ({ name, questions: 1, answered: score === null ? 0 : 1, points_possible: 6, points_earned: 6, critical_gaps: 0, raw: score, score, rating: score === null ? 'na' : score >= 0.95 ? 'green' : score >= 0.85 ? 'amber' : 'red', ...over }) as RiskAggregate;
const card = (over: Partial<RiskScorecard> = {}): RiskScorecard =>
  ({
    overall: null, rating: 'na', gaps: [], gap_count: 0, total: 3, answered: 0, open: 3, unknown: 0, alternative_vendors: 0, settings: SETTINGS,
    categories: [
      { ...agg('Administrative', null), weight: 8, excluded: false, sections: [agg('Onboarding', null)] },
      { ...agg('Network & Infrastructure', null), weight: 12, excluded: false, sections: [agg('Firewalls', null)] },
      { ...agg('Google Workspace', null), weight: 20, excluded: true, sections: [] },
    ],
    csf: [agg('Govern', null), agg('Protect', null), agg('Respond', null, { questions: 0 })],
    ...over,
  }) as RiskScorecard;
const assessment = (over: Partial<RiskAssessment> = {}): RiskAssessment => ({ id: 'a1', client_id: 'c1', client_name: 'Acme Dental', review_date: '2026-11-12', platform: 'm365', assessor: 'Hal', score: null, rating: 'na', answered: 0, updated_at: '2026-11-12T10:00:00Z', updated_by: 'hal', answers: {}, severity: {}, scorecard: card(), ...over });
const summary = (a: RiskAssessment) => ({ id: a.id, client_id: a.client_id, client_name: a.client_name, review_date: a.review_date, platform: a.platform, assessor: a.assessor, score: a.score, rating: a.rating, answered: a.answered, updated_at: a.updated_at, updated_by: a.updated_by });

beforeEach(() => {
  for (const f of Object.values(api)) f.mockReset();
  mssp.listChildren.mockReset().mockResolvedValue([{ id: 'c2', name: 'Birch Law', mssp_role: 'child' }, { id: 'c1', name: 'Acme Dental', mssp_role: 'child' }]);
  csv.downloadCsv.mockReset();
  api.library.mockResolvedValue(LIBRARY);
  api.assessors.mockResolvedValue({ items: [{ name: 'Dana', email: 'dana@example.test' }, { name: 'Hal', email: null }] });
  api.trends.mockResolvedValue({ clients: [] });
  api.clientTrend.mockResolvedValue({ client_id: 'c1', client_name: 'Acme Dental', points: [], categories: [] });
});

const pickClient = async () => userEvent.selectOptions(await screen.findByLabelText('Client'), 'c1');

describe('the pure parts', () => {
  it('shows a score as a whole percentage and a dash for nothing', () => {
    expect([pct(0.846), pct(1), pct(0), pct(null)]).toEqual(['85%', '100%', '0%', '—']);
  });

  it('knows which answers lose points: the wrong one, Partial and Unknown, never N/A, and an alternative vendor keeps its points', () => {
    const [yes, rdp, vendor] = QUESTIONS;
    expect([losesPoints(yes, 'Yes'), losesPoints(yes, 'No'), losesPoints(yes, 'Partial'), losesPoints(yes, 'Unknown'), losesPoints(yes, 'N/A'), losesPoints(yes, null)]).toEqual([false, true, true, true, false, false]);
    expect([losesPoints(rdp, 'No'), losesPoints(rdp, 'Yes')]).toEqual([false, true]);
    expect([losesPoints(vendor, 'Preferred'), losesPoints(vendor, 'Alternative'), losesPoints(vendor, 'None')]).toEqual([false, false, true]);
  });

  it('never shows the other platform’s questions, and each filter keeps what it says', () => {
    const a = assessment({ answers: { 'ADM-001': { answer: 'No' }, 'TS-001': { answer: 'Unknown' } } });
    const ids = (opts: Partial<Parameters<typeof keepQuestions>[2]>) => keepQuestions(QUESTIONS, a, { filter: 'all', category: '', search: '', ...opts }).map((x) => x.id);
    expect(ids({})).toEqual(['ADM-001', 'NET-002', 'TS-001']);
    expect(keepQuestions(QUESTIONS, { ...a, platform: 'both' }, { filter: 'all', category: '', search: '' })).toHaveLength(4);
    expect(excludedFor({ category: 'Microsoft 365' }, 'google')).toBe(true);
    expect(ids({ filter: 'open' })).toEqual(['NET-002']);
    expect(ids({ filter: 'gaps' })).toEqual(['ADM-001', 'TS-001']);
    expect(ids({ filter: 'unknown' })).toEqual(['TS-001']);
    expect(ids({ filter: 'critical' })).toEqual(['NET-002']);
    expect(keepQuestions(QUESTIONS, { ...a, severity: { 'ADM-001': 'Critical' } }, { filter: 'critical', category: '', search: '' }).map((x) => x.id)).toEqual(['ADM-001', 'NET-002']);
    expect(ids({ category: 'Tech Stack' })).toEqual(['TS-001']);
    expect(ids({ search: ' rdp ' })).toEqual(['NET-002']);
    expect(keepQuestions(QUESTIONS, { ...a, answers: { 'NET-002': { answer: 'No', source: 'auto' }, 'ADM-001': { answer: 'No' } } }, { filter: 'auto', category: '', search: '' }).map((x) => x.id)).toEqual(['NET-002']);
  });

  it('says in one sentence what a fill from the integrations did', () => {
    const r = { filled: 12, changed: 1, kept_by_hand: 3, cleared: 2, answered_by_integrations: 16 };
    expect(autofillSentence(r)).toBe('12 answers filled in from the integrations, 1 updated, 3 you set by hand left as they are, 2 taken out because the integrations no longer say.');
    expect(autofillSentence({ filled: 0, changed: 0, kept_by_hand: 0, cleared: 0, answered_by_integrations: 0 })).toBe('The integrations have no answer for this client yet: nothing was filled in.');
    expect(autofillSentence({ filled: 1, changed: 0, kept_by_hand: 0, cleared: 0, answered_by_integrations: 1 })).toBe('1 answer filled in from the integrations.');
  });

  it('says a change as an arrow and points, and nothing when there is nothing to compare', () => {
    expect([changeText(8, 'up'), changeText(-3.5, 'down'), changeText(1, 'up'), changeText(0.2, 'flat'), changeText(null, 'none'), changeText(5, 'none')]).toEqual(['▲ 8 points', '▼ 3.5 points', '▲ 1 point', 'no change', '', '']);
  });

  it('offers the organisation’s users as assessor, and keeps a name an old assessment carries', () => {
    const users = [{ name: 'Dana', email: null }, { name: 'Hal', email: null }];
    expect(assessorChoices(users, 'Hal')).toEqual(['Dana', 'Hal']);
    expect(assessorChoices(users, 'hal')).toEqual(['Dana', 'Hal']);
    expect(assessorChoices(users, 'Someone Who Left')).toEqual(['Dana', 'Hal', 'Someone Who Left']);
    expect(assessorChoices(users, '')).toEqual(['Dana', 'Hal']);
  });

  it('writes the assessment as a CSV, one row per question the client is asked', () => {
    const rows = assessmentCsv(QUESTIONS, assessment({ answers: { 'TS-001': { answer: 'Alternative', vendor: 'Fortinet', note: 'renew in May' } }, severity: { 'ADM-001': 'Low' } })).trim().split(/\r?\n/);
    expect(rows).toHaveLength(4);
    expect(rows[0].replace('﻿', '')).toBe('ID,Category,Section,Question,Severity,Good answer,Answer,Vendor / product in use,Evidence / notes,NIST CSF 2.0,CSF function,Answer source,What the integrations saw');
    expect(rows[1]).toBe('ADM-001,Administrative,Onboarding,Is there an onboarding plan?,Low,Yes,,,,GV.RR,Govern,,');
    expect(rows[3]).toBe('TS-001,Tech Stack,Network Equipment,What is the client firewall?,Medium,Preferred,Alternative,Fortinet,renew in May,GV.RR,Govern,Typed,');
    const auto = assessmentCsv(QUESTIONS, assessment({ answers: { 'ADM-001': { answer: 'Yes', source: 'auto', evidence: 'From a check' } } })).trim().split(/\r?\n/);
    expect(auto[1]).toBe('ADM-001,Administrative,Onboarding,Is there an onboarding plan?,High,Yes,Yes,,,GV.RR,Govern,Integrations,From a check');
  });
});

describe('RiskScoringView', () => {
  it('asks for a client first, and says so when the client has no assessment yet', async () => {
    api.list.mockResolvedValue({ items: [] });
    render(<RiskScoringView />);
    expect(await screen.findByText(/Choose a client to see/)).toBeInTheDocument();
    expect(api.list).not.toHaveBeenCalled();
    await pickClient();
    expect(await screen.findByTestId('risk-none')).toHaveTextContent('No assessment for Acme Dental yet');
    expect(api.list).toHaveBeenCalledWith('c1');
  });

  it('starts an assessment with a date, platform and assessor, and opens it on the questions', async () => {
    api.list.mockResolvedValueOnce({ items: [] });
    const made = assessment({ platform: 'both', assessor: 'Dana' });
    api.create.mockResolvedValue(made);
    api.list.mockResolvedValue({ items: [summary(made)] });
    api.get.mockResolvedValue(made);
    render(<RiskScoringView />);
    await pickClient();
    await userEvent.click(await screen.findByRole('button', { name: 'New assessment' }));
    const dialog = within(screen.getByRole('dialog', { name: 'New assessment' }));
    await userEvent.selectOptions(dialog.getByLabelText('New platform'), 'both');
    expect(within(dialog.getByLabelText('New assessor')).getAllByRole('option').map((o) => o.textContent)).toEqual(['Not set', 'Dana', 'Hal']);
    await userEvent.selectOptions(dialog.getByLabelText('New assessor'), 'Dana');
    await userEvent.click(dialog.getByRole('button', { name: 'Start' }));
    await waitFor(() => expect(api.create).toHaveBeenCalledWith(expect.objectContaining({ client_id: 'c1', platform: 'both', assessor: 'Dana' })));
    expect(api.create.mock.calls[0][0].review_date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(await screen.findAllByTestId('risk-question')).toHaveLength(4);
    expect(api.get).toHaveBeenCalledWith('a1');
  });

  it('shows the scorecard: overall, each category with its sections, a capped category, the NIST reading and the gaps', async () => {
    const scored = assessment({
      score: 0.62, rating: 'red', answered: 2,
      scorecard: card({
        overall: 0.62, rating: 'red', answered: 2, open: 1, gap_count: 1,
        gaps: [{ id: 'NET-002', severity: 'Critical', answer: 'Yes', points_lost: 10 }],
        categories: [
          { ...agg('Administrative', 1), weight: 8, excluded: false, sections: [agg('Onboarding', 1)] },
          { ...agg('Network & Infrastructure', 0, { critical_gaps: 1 }), weight: 12, excluded: false, sections: [agg('Firewalls', 0)] },
          { ...agg('Google Workspace', null), weight: 20, excluded: true, sections: [] },
        ],
      }),
    });
    api.list.mockResolvedValue({ items: [summary(scored)] });
    api.get.mockResolvedValue(scored);
    render(<RiskScoringView />);
    await pickClient();
    expect(await screen.findByTestId('risk-overall')).toHaveTextContent('62%');
    const categories = screen.getAllByTestId('risk-category');
    expect(categories.some((c) => c.textContent?.includes('Administrative (weight 8)') && c.textContent.includes('100%'))).toBe(true);
    expect(categories.some((c) => c.textContent?.includes('Google Workspace'))).toBe(false);
    expect(screen.getByTestId('risk-cap-note')).toHaveTextContent('Network & Infrastructure: 1 critical gap, capped at 84%');
    expect(screen.getAllByTestId('risk-csf').map((r) => r.textContent)).toEqual(expect.arrayContaining([expect.stringContaining('Respond (no questions)')]));
    const gap = screen.getByTestId('risk-gap');
    expect(gap).toHaveTextContent('Is RDP port 3389 exposed?');
    expect(gap).toHaveTextContent('Critical');
    expect(gap).toHaveTextContent('10');
  });

  it('answering a question sends it and shows the scorecard the API sends back; pressing the same answer again clears it', async () => {
    const start = assessment();
    const answered = assessment({ answers: { 'ADM-001': { answer: 'Yes' } }, answered: 1, score: 1, rating: 'green', scorecard: card({ overall: 1, rating: 'green', answered: 1 }) });
    api.list.mockResolvedValue({ items: [summary(start)] });
    api.get.mockResolvedValue(start);
    api.answer.mockResolvedValueOnce(answered).mockResolvedValueOnce(start);
    render(<RiskScoringView />);
    await pickClient();
    await userEvent.click(await screen.findByRole('tab', { name: 'Questions' }));
    const first = (await screen.findAllByTestId('risk-question'))[0];
    await userEvent.click(within(first).getByRole('button', { name: 'Yes' }));
    await waitFor(() => expect(api.answer).toHaveBeenCalledWith('a1', [{ id: 'ADM-001', answer: 'Yes', vendor: null, note: null }]));
    await waitFor(() => expect(within(screen.getAllByTestId('risk-question')[0]).getByRole('button', { name: 'Yes' })).toHaveAttribute('aria-pressed', 'true'));
    await userEvent.click(within(screen.getAllByTestId('risk-question')[0]).getByRole('button', { name: 'Yes' }));
    await waitFor(() => expect(api.answer).toHaveBeenLastCalledWith('a1', [{ id: 'ADM-001', answer: null, vendor: null, note: null }]));
    await userEvent.click(screen.getByRole('tab', { name: 'Scorecard' }));
    expect(screen.getByTestId('risk-overall')).toHaveTextContent('—');
  });

  it('a vendor question offers Preferred, Alternative and None and keeps the product in use; a note and a severity change are saved too', async () => {
    const start = assessment();
    api.list.mockResolvedValue({ items: [summary(start)] });
    api.get.mockResolvedValue(start);
    api.answer.mockResolvedValue(start);
    api.update.mockResolvedValue(assessment({ severity: { 'ADM-001': 'Low' } }));
    render(<RiskScoringView />);
    await pickClient();
    await userEvent.click(await screen.findByRole('tab', { name: 'Questions' }));
    const rows = await screen.findAllByTestId('risk-question');
    const vendor = rows[2];
    expect(within(vendor).getByRole('button', { name: 'Alternative' })).toBeInTheDocument();
    expect(within(vendor).queryByRole('button', { name: 'Yes' })).toBeNull();
    await userEvent.type(within(vendor).getByLabelText('Vendor or product in use for TS-001'), 'Fortinet');
    await userEvent.tab();
    await waitFor(() => expect(api.answer).toHaveBeenCalledWith('a1', [{ id: 'TS-001', answer: null, vendor: 'Fortinet', note: null }]));
    await userEvent.click(within(rows[0]).getByRole('button', { name: 'Add note' }));
    await userEvent.type(within(rows[0]).getByLabelText('Evidence or notes for ADM-001'), 'in IT Glue');
    await userEvent.tab();
    await waitFor(() => expect(api.answer).toHaveBeenLastCalledWith('a1', [{ id: 'ADM-001', answer: null, vendor: null, note: 'in IT Glue' }]));
    await userEvent.selectOptions(within(rows[0]).getByLabelText('Severity of ADM-001'), 'Low');
    await waitFor(() => expect(api.update).toHaveBeenCalledWith('a1', { severity: { 'ADM-001': 'Low' } }));
  });

  it('has no settings on this page: they are under Settings, for the people who may change them', async () => {
    const start = assessment();
    api.list.mockResolvedValue({ items: [summary(start)] });
    api.get.mockResolvedValue(start);
    render(<RiskScoringView />);
    await pickClient();
    await screen.findByTestId('risk-overall');
    expect(screen.queryByRole('tab', { name: 'Settings' })).toBeNull();
    expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual(['Scorecard', 'Questions', 'Method']);
    await userEvent.click(screen.getByRole('tab', { name: 'Method' }));
    expect(screen.getByTestId('risk-method')).toHaveTextContent('Settings > Client Risk Score');
  });

  it('Fill from integrations asks the API, shows the answers it sends back marked Auto with what the tool saw, and says what it did', async () => {
    const start = assessment({ answers: { 'ADM-001': { answer: 'No' } } });
    const filled = assessment({ answers: { 'ADM-001': { answer: 'No' }, 'NET-002': { answer: 'No', source: 'auto', evidence: 'From threatmate_external_exposure. No issues found.' } }, answered: 2, score: 0.5, rating: 'red' });
    api.list.mockResolvedValue({ items: [summary(start)] });
    api.get.mockResolvedValue(start);
    api.autofill.mockResolvedValue({ assessment: filled, filled: 1, changed: 0, kept_by_hand: 1, cleared: 0, answered_by_integrations: 2 });
    render(<RiskScoringView />);
    await pickClient();
    await userEvent.click(await screen.findByRole('button', { name: 'Fill from integrations' }));
    await waitFor(() => expect(api.autofill).toHaveBeenCalledWith('a1'));
    expect(await screen.findByTestId('risk-notice')).toHaveTextContent('1 answer filled in from the integrations, 1 you set by hand left as it is.');
    await userEvent.click(screen.getByRole('tab', { name: 'Questions' }));
    const rows = await screen.findAllByTestId('risk-question');
    expect(within(rows[1]).getByTestId('risk-auto')).toHaveTextContent('Auto');
    expect(within(rows[1]).getByTestId('risk-evidence')).toHaveTextContent('From threatmate_external_exposure. No issues found.');
    expect(within(rows[0]).queryByTestId('risk-auto')).toBeNull();
    await userEvent.selectOptions(screen.getByLabelText('Which questions'), 'auto');
    expect(screen.getAllByTestId('risk-question')).toHaveLength(1);
  });

  it('a new assessment is filled from the integrations unless the box is unticked', async () => {
    const made = assessment();
    api.list.mockResolvedValueOnce({ items: [] }).mockResolvedValue({ items: [summary(made)] });
    api.create.mockResolvedValue(made);
    api.get.mockResolvedValue(made);
    api.autofill.mockResolvedValue({ assessment: made, filled: 0, changed: 0, kept_by_hand: 0, cleared: 0, answered_by_integrations: 0 });
    render(<RiskScoringView />);
    await pickClient();
    await userEvent.click(await screen.findByRole('button', { name: 'New assessment' }));
    expect(screen.getByLabelText('Fill in what the integrations can answer')).toBeChecked();
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Start' }));
    await waitFor(() => expect(api.autofill).toHaveBeenCalledWith('a1'));
    expect(await screen.findByTestId('risk-notice')).toHaveTextContent('The integrations have no answer for this client yet');
    api.autofill.mockClear();
    await userEvent.click(screen.getByRole('button', { name: 'New assessment' }));
    await userEvent.click(screen.getByLabelText('Fill in what the integrations can answer'));
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Start' }));
    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(api.autofill).not.toHaveBeenCalled();
  });

  it('exports the open assessment, explains the method, and deletes only after a yes', async () => {
    const start = assessment();
    api.list.mockResolvedValueOnce({ items: [summary(start)] }).mockResolvedValue({ items: [] });
    api.get.mockResolvedValue(start);
    api.remove.mockResolvedValue({ deleted: true });
    render(<RiskScoringView />);
    await pickClient();
    await userEvent.click(await screen.findByRole('button', { name: 'Export CSV' }));
    expect(csv.downloadCsv.mock.calls[0][0]).toBe('vcio-risk-scoring-acme-dental-2026-11-12.csv');
    await userEvent.click(screen.getByRole('tab', { name: 'Method' }));
    expect(screen.getByTestId('risk-method')).toHaveTextContent('Critical = 10 points, High = 6, Medium = 3, Low = 1');
    await userEvent.click(screen.getByRole('button', { name: 'Delete assessment' }));
    await userEvent.click(screen.getByRole('button', { name: 'No, keep it' }));
    expect(api.remove).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Delete assessment' }));
    await userEvent.click(screen.getByRole('button', { name: 'Yes, delete' }));
    await waitFor(() => expect(api.remove).toHaveBeenCalledWith('a1'));
    expect(await screen.findByTestId('risk-none')).toBeInTheDocument();
  });

  it('shows the API’s reason when a change is refused, and keeps what was on the page', async () => {
    const start = assessment();
    api.list.mockResolvedValue({ items: [summary(start)] });
    api.get.mockResolvedValue(start);
    api.answer.mockRejectedValue(new ApiError('403', 403, JSON.stringify({ detail: 'You do not have permission to change client reviews.' })));
    render(<RiskScoringView />);
    await pickClient();
    await userEvent.click(await screen.findByRole('tab', { name: 'Questions' }));
    await userEvent.click(within((await screen.findAllByTestId('risk-question'))[0]).getByRole('button', { name: 'No' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('You do not have permission to change client reviews.');
    expect(within(screen.getAllByTestId('risk-question')[0]).getByRole('button', { name: 'No' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('the assessor is picked from the A.C.O.R.N users, and a name an old assessment carries stays on the list', async () => {
    const old = assessment({ assessor: 'Someone Who Left' });
    api.list.mockResolvedValue({ items: [summary(old)] });
    api.get.mockResolvedValue(old);
    api.update.mockResolvedValue(assessment({ assessor: 'Dana' }));
    render(<RiskScoringView />);
    await pickClient();
    const pick = await screen.findByLabelText('Assessor');
    await waitFor(() => expect(within(pick).getAllByRole('option').map((o) => o.textContent)).toEqual(['Not set', 'Dana', 'Hal', 'Someone Who Left']));
    expect(pick).toHaveValue('Someone Who Left');
    await userEvent.selectOptions(pick, 'Dana');
    await waitFor(() => expect(api.update).toHaveBeenCalledWith('a1', { assessor: 'Dana' }));
    await waitFor(() => expect(screen.getByLabelText('Assessor')).toHaveValue('Dana'));
  });

  it('shows the client’s trend: each assessment with how far it moved, the change on the overall score, and where it moved', async () => {
    const now = assessment({ id: 'a2', review_date: '2026-11-12', score: 0.9, rating: 'amber', answered: 40, scorecard: card({ overall: 0.9, rating: 'amber', answered: 40 }) });
    api.list.mockResolvedValue({ items: [summary(now)] });
    api.get.mockResolvedValue(now);
    api.clientTrend.mockResolvedValue({
      client_id: 'c1', client_name: 'Acme Dental',
      points: [
        { id: 'a0', review_date: '2026-03-01', score: 0.7, rating: 'red', answered: 30, assessor: 'Dana', change: null, direction: 'none', compared_with: null, categories: {} },
        { id: 'a1', review_date: '2026-06-01', score: null, rating: 'na', answered: 0, assessor: '', change: null, direction: 'none', compared_with: null, categories: {} },
        { id: 'a2', review_date: '2026-11-12', score: 0.9, rating: 'amber', answered: 40, assessor: 'Hal', change: 20, direction: 'up', compared_with: '2026-03-01', categories: {} },
      ],
      categories: [{ name: 'Tech Stack', before: 1, after: 0.5, change: -50, direction: 'down' }, { name: 'Administrative', before: 0.4, after: 1, change: 60, direction: 'up' }],
    });
    render(<RiskScoringView />);
    await pickClient();
    await waitFor(() => expect(api.clientTrend).toHaveBeenCalledWith('c1'));
    expect(await screen.findByTestId('risk-overall-change')).toHaveTextContent('▲ 20 points since 2026-03-01');
    const points = screen.getAllByTestId('risk-trend-point');
    expect(points.map((p) => p.textContent)).toEqual([
      expect.stringContaining('2026-11-12 (open)90%▲ 20 points40Hal'),
      expect.stringContaining('2026-06-01—nothing answered0—'),
      expect.stringContaining('2026-03-0170%first assessment30Dana'),
    ]);
    expect(screen.getByTestId('risk-trend-categories')).toHaveTextContent('Tech Stack100% → 50% · ▼ 50 points');
    expect(screen.getByTestId('risk-trend-categories')).toHaveTextContent('Administrative40% → 100% · ▲ 60 points');
    api.get.mockResolvedValue(assessment({ id: 'a0', review_date: '2026-03-01' }));
    await userEvent.click(within(points[2]).getByRole('button', { name: '2026-03-01' }));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('a0'));
  });

  it('says the trend starts with the second assessment when the client has only one', async () => {
    const only = assessment();
    api.list.mockResolvedValue({ items: [summary(only)] });
    api.get.mockResolvedValue(only);
    api.clientTrend.mockResolvedValue({ client_id: 'c1', client_name: 'Acme Dental', points: [{ id: 'a1', review_date: '2026-11-12', score: null, rating: 'na', answered: 0, assessor: '', change: null, direction: 'none', compared_with: null, categories: {} }], categories: [] });
    render(<RiskScoringView />);
    await pickClient();
    expect(await screen.findByTestId('risk-trend')).toHaveTextContent('The trend appears from the second one on');
    expect(screen.queryByTestId('risk-overall-change')).toBeNull();
  });

  it('before a client is chosen, lists every assessed client with its score and how it moved, and opens the one pressed', async () => {
    api.trends.mockResolvedValue({
      clients: [
        { client_id: 'c2', client_name: 'Birch Law', assessments: 3, latest_date: '2026-10-01', latest_score: 0.6, rating: 'red', previous_date: '2026-04-01', previous_score: 0.8, change: -20, direction: 'down' },
        { client_id: 'c1', client_name: 'Acme Dental', assessments: 2, latest_date: '2026-11-12', latest_score: 0.96, rating: 'green', previous_date: '2026-05-01', previous_score: 0.9, change: 6, direction: 'up' },
        { client_id: 'own', client_name: null, assessments: 1, latest_date: '2026-01-01', latest_score: null, rating: 'na', previous_date: null, previous_score: null, change: null, direction: 'none' },
      ],
    });
    api.list.mockResolvedValue({ items: [] });
    render(<RiskScoringView />);
    const box = await screen.findByTestId('risk-all-clients');
    expect(box).toHaveTextContent('3 assessed: 1 down, 1 up since their assessment before');
    expect(screen.getAllByTestId('risk-client-row').map((r) => r.textContent)).toEqual(['Birch Law60%▼ 20 points2026-10-013', 'Acme Dental96%▲ 6 points2026-11-122', 'Own organisation—first assessment2026-01-011']);
    await userEvent.click(within(box).getByRole('button', { name: 'Birch Law' }));
    await waitFor(() => expect(api.list).toHaveBeenCalledWith('c2'));
    expect(screen.queryByTestId('risk-all-clients')).toBeNull();
  });
});
