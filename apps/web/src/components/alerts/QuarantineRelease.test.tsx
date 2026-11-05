import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ quarantine: vi.fn(), releaseQuarantine: vi.fn(), checkQuarantine: vi.fn(), toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/lib/api', () => ({ alertsApi: { quarantine: api.quarantine, releaseQuarantine: api.releaseQuarantine, checkQuarantine: api.checkQuarantine } }));
vi.mock('react-hot-toast', () => ({ default: api.toast }));

import { QuarantineRelease, checkLines, releaseStateText } from './QuarantineRelease';

const info = (over: Record<string, unknown> = {}) => ({ available: true, recipient: 'kim@acme.com', sender: 'ceo@lookalike.example', kind: 'HighConfPhish', state: 'none', ...over });
const show = () =>
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
      <QuarantineRelease alertId="a1" />
    </SWRConfig>,
  );

beforeEach(() => {
  api.quarantine.mockReset();
  api.releaseQuarantine.mockReset();
  api.checkQuarantine.mockReset();
  api.toast.success.mockReset();
  api.toast.error.mockReset();
});

describe('QuarantineRelease', () => {
  it('shows nothing for an alert that is not about a quarantined message', async () => {
    api.quarantine.mockResolvedValue({ available: false, state: 'none' });
    show();
    await waitFor(() => expect(api.quarantine).toHaveBeenCalledWith('a1'));
    expect(screen.queryByTestId('quarantine-release')).toBeNull();
  });

  it('says who the message was for and from, and why it was held', async () => {
    api.quarantine.mockResolvedValue(info());
    show();
    const box = await screen.findByTestId('quarantine-release');
    expect(box).toHaveTextContent('Held for kim@acme.com from ceo@lookalike.example (held as HighConfPhish).');
  });

  it('asks before releasing, sends nothing on cancel, and releases only after the confirmation', async () => {
    api.quarantine.mockResolvedValue(info());
    api.releaseQuarantine.mockResolvedValue(info({ state: 'pending' }));
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole('button', { name: 'Release this message…' }));
    expect(api.releaseQuarantine).not.toHaveBeenCalled();
    expect(screen.getByText(/Only release it if you are sure it is safe/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(api.releaseQuarantine).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Release this message…' }));
    await user.click(screen.getByRole('button', { name: 'Confirm release' }));
    await waitFor(() => expect(api.releaseQuarantine).toHaveBeenCalledWith('a1'));
    expect(await screen.findByTestId('release-state')).toHaveTextContent('waiting for CORE');
    expect(screen.queryByRole('button', { name: 'Release this message…' })).toBeNull();
  });

  it('shows a finished release with no button, and a failed one with the reason and a way to try again', async () => {
    api.quarantine.mockResolvedValue(info({ state: 'done', message: 'Released. Successfully processed' }));
    const a = show();
    expect(await screen.findByTestId('release-state')).toHaveTextContent('Released. Successfully processed');
    expect(screen.queryByRole('button', { name: /Release this message|Try releasing again/ })).toBeNull();
    a.unmount();
    api.quarantine.mockResolvedValue(info({ state: 'failed', message: 'Refused by CORE: this client is not opted in' }));
    show();
    expect(await screen.findByTestId('release-state')).toHaveTextContent('Not released: Refused by CORE: this client is not opted in');
    expect(screen.getByRole('button', { name: 'Try releasing again…' })).toBeInTheDocument();
  });

  it('says what the server refused when the request fails', async () => {
    api.quarantine.mockResolvedValue(info());
    api.releaseQuarantine.mockRejectedValueOnce(new Error('A release for this message is already waiting for CORE'));
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole('button', { name: 'Release this message…' }));
    await user.click(screen.getByRole('button', { name: 'Confirm release' }));
    await waitFor(() => expect(api.toast.error).toHaveBeenCalledWith('A release for this message is already waiting for CORE'));
  });
});

describe('releaseStateText', () => {
  it('reads each state in plain words', () => {
    const t = (state: string, message?: string) => releaseStateText({ available: true, state, message } as never).text;
    expect(t('pending')).toMatch(/waiting for CORE/);
    expect(t('claimed')).toMatch(/releasing it through CIPP/);
    expect(t('done')).toBe('Released.');
    expect(t('failed')).toBe('Not released: CORE did not say why.');
    expect(t('none')).toBe('');
  });
});

const TEXT = 'Looks malicious or fake: do not release it.\n[BAD] Sender checks: SPF fail, DKIM none, DMARC fail (action reject)\n[CHECK] Replies go elsewhere: the reply address is at elsewhere.example\n[-] Why Microsoft held it: classified as spam\n[OK] Something fine: ok';

describe('checkLines', () => {
  it('splits the advice from the findings and reads each mark', () => {
    const c = checkLines(TEXT);
    expect(c.advice).toBe('Looks malicious or fake: do not release it.');
    expect(c.findings.map((f) => [f.word, f.text.slice(0, 20)])).toEqual([
      ['bad', 'Sender checks: SPF f'],
      ['check', 'Replies go elsewhere'],
      ['info', 'Why Microsoft held i'],
      ['ok', 'Something fine: ok'],
    ]);
    expect(checkLines('Only an advice').findings).toEqual([]);
    expect(checkLines('Advice\nplain line without a mark').findings[0]).toMatchObject({ word: 'info', text: 'plain line without a mark' });
  });
});

describe('checking why it was held', () => {
  it('offers the check, asks for it, and shows CORE as looking', async () => {
    api.quarantine.mockResolvedValue(info({ check_state: 'none' }));
    api.checkQuarantine.mockResolvedValue(info({ check_state: 'pending' }));
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole('button', { name: 'Check why it was held' }));
    await waitFor(() => expect(api.checkQuarantine).toHaveBeenCalledWith('a1'));
  });

  it('shows what was found: the advice first, then each finding marked', async () => {
    api.quarantine.mockResolvedValue(info({ check_state: 'done', check_text: TEXT }));
    show();
    expect(await screen.findByTestId('check-advice')).toHaveTextContent('Looks malicious or fake: do not release it.');
    const findings = screen.getAllByTestId('check-finding');
    expect(findings).toHaveLength(4);
    expect(findings[0]).toHaveTextContent('bad');
    expect(findings[0]).toHaveTextContent('SPF fail, DKIM none, DMARC fail');
    expect(screen.getByRole('button', { name: 'Check again' })).toBeInTheDocument();
  });

  it('says while CORE is looking, with no button, and says why a check failed', async () => {
    api.quarantine.mockResolvedValue(info({ check_state: 'claimed' }));
    const a = show();
    expect(await screen.findByText('CORE is looking into why it was held…')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Check why it was held|Check again/ })).toBeNull();
    a.unmount();
    api.quarantine.mockResolvedValue(info({ check_state: 'failed', check_text: 'Microsoft 365 does not list this message any more.' }));
    show();
    expect(await screen.findByText(/Could not check it: Microsoft 365 does not list this message any more\./)).toBeInTheDocument();
  });

  it('offers no check from a server that does not know about it, and says what was refused', async () => {
    api.quarantine.mockResolvedValue(info());
    const a = show();
    await screen.findByTestId('quarantine-release');
    expect(screen.queryByRole('button', { name: 'Check why it was held' })).toBeNull();
    a.unmount();
    api.quarantine.mockResolvedValue(info({ check_state: 'none' }));
    api.checkQuarantine.mockRejectedValueOnce(new Error('A check for this message is already waiting for CORE'));
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole('button', { name: 'Check why it was held' }));
    await waitFor(() => expect(api.toast.error).toHaveBeenCalledWith('A check for this message is already waiting for CORE'));
  });
});
