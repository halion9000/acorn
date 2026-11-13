import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ settings: vi.fn(), saveSettings: vi.fn() }));
vi.mock('@/lib/vcioRisk', async (original) => ({ ...(await original<typeof import('@/lib/vcioRisk')>()), vcioRiskApi: api }));

import { ApiError } from '@/lib/api';
import type { RiskSettings, RiskSettingsAnswer } from '@/lib/vcioRisk';
import { VcioRiskSettings } from './VcioRiskSettings';

const DEFAULTS: RiskSettings = { points: { Critical: 10, High: 6, Medium: 3, Low: 1 }, partial: 0.5, unknown: 0, alternative: 1, cap_on: true, cap: 0.84, green: 0.95, amber: 0.85, weights: { Administrative: 8, 'Tech Stack': 15 } };
const answer = (over: Partial<RiskSettingsAnswer> = {}): RiskSettingsAnswer => ({ settings: DEFAULTS, defaults: DEFAULTS, using_defaults: true, rescored: 0, ...over });

beforeEach(() => {
  api.settings.mockReset().mockResolvedValue(answer());
  api.saveSettings.mockReset();
});

describe('VcioRiskSettings', () => {
  it('shows the organisation’s settings and says the defaults are in use', async () => {
    render(<VcioRiskSettings />);
    expect(await screen.findByLabelText('Critical points')).toHaveValue(10);
    expect(screen.getByLabelText('Cap the category at')).toHaveValue(0.84);
    expect(screen.getByLabelText('Tech Stack')).toHaveValue(15);
    expect(screen.getByLabelText('Apply the critical-gap cap')).toBeChecked();
    expect(screen.getByTestId('vcio-risk-settings')).toHaveTextContent('One set for all clients');
    expect(screen.getByTestId('vcio-risk-settings')).toHaveTextContent('The defaults are in use.');
  });

  it('saves what was changed and says how many assessments were scored again', async () => {
    const changed = { ...DEFAULTS, points: { ...DEFAULTS.points, Critical: 20 } };
    api.saveSettings.mockResolvedValue(answer({ settings: changed, using_defaults: false, rescored: 7 }));
    render(<VcioRiskSettings />);
    const points = await screen.findByLabelText('Critical points');
    await userEvent.clear(points);
    await userEvent.type(points, '20');
    await userEvent.click(screen.getByRole('button', { name: 'Save settings' }));
    await waitFor(() => expect(api.saveSettings).toHaveBeenCalledTimes(1));
    expect(api.saveSettings.mock.calls[0][0].points.Critical).toBe(20);
    expect(await screen.findByRole('status')).toHaveTextContent('Saved. 7 assessments scored again.');
    expect(screen.getByTestId('vcio-risk-settings')).toHaveTextContent('These differ from the defaults.');
  });

  it('Reset to defaults sends nothing to keep, and shows the defaults again', async () => {
    api.settings.mockResolvedValue(answer({ settings: { ...DEFAULTS, cap: 0.7 }, using_defaults: false }));
    api.saveSettings.mockResolvedValue(answer({ rescored: 1 }));
    render(<VcioRiskSettings />);
    expect(await screen.findByLabelText('Cap the category at')).toHaveValue(0.7);
    await userEvent.click(screen.getByRole('button', { name: 'Reset to defaults' }));
    await waitFor(() => expect(api.saveSettings).toHaveBeenCalledWith({}));
    expect(await screen.findByRole('status')).toHaveTextContent('Back to the defaults. 1 assessment scored again.');
    expect(screen.getByLabelText('Cap the category at')).toHaveValue(0.84);
  });

  it('shows the reason when a person may not see or change the settings, and no form', async () => {
    api.settings.mockRejectedValue(new ApiError('403', 403, JSON.stringify({ detail: 'You do not have permission to see settings.' })));
    render(<VcioRiskSettings />);
    expect(await screen.findByRole('alert')).toHaveTextContent('You do not have permission to see settings.');
    expect(screen.queryByLabelText('Critical points')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Save settings' })).toBeNull();
  });
});
