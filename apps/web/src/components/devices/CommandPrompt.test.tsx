import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ consoleHistory: vi.fn(), consoleSend: vi.fn(), consoleLine: vi.fn() }));
vi.mock('@/lib/api', () => ({ apiErrorDetail: (e: unknown) => (e instanceof Error ? e.message : null), devicesApi: api }));

import { CommandPrompt } from './CommandPrompt';

const line = (over: Record<string, unknown> = {}) => ({ request_id: 'r1', command: 'hostname', status: 'pending', output: null, requested_at: '2026-11-14T10:00:00Z', finished_at: null, ...over });
const history = (over: Record<string, unknown> = {}) => ({ device_id: 'd1', device: 'PC-1', available: true, blocked: null, lines: [], ...over });

beforeEach(() => {
  Object.values(api).forEach((m) => m.mockReset());
  api.consoleHistory.mockResolvedValue(history());
});

describe('CommandPrompt', () => {
  it('is a button until opened, then a prompt that shows the machine and says it runs as SYSTEM and is logged', async () => {
    render(<CommandPrompt deviceId="d1" hostname="PC-1" />);
    expect(api.consoleHistory).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Open command prompt' }));
    expect(await screen.findByText(/runs as SYSTEM through ScreenConnect; every command is logged/)).toBeTruthy();
    expect(api.consoleHistory).toHaveBeenCalledWith('d1');
  });

  it('sends the typed command on Enter, shows it waiting, then prints the machine answer when it comes', async () => {
    api.consoleSend.mockResolvedValue(line());
    render(<CommandPrompt deviceId="d1" hostname="PC-1" />);
    await userEvent.click(screen.getByRole('button', { name: 'Open command prompt' }));
    const box = await screen.findByLabelText('Command');
    await userEvent.type(box, 'hostname{Enter}');
    expect(api.consoleSend).toHaveBeenCalledWith('d1', 'hostname');
    expect(await screen.findByText('waiting for the machine...')).toBeTruthy();
    expect((screen.getByLabelText('Command') as HTMLInputElement).disabled).toBe(true);
    api.consoleLine.mockResolvedValue(line({ status: 'done', output: 'PC-1\nsecond line' }));
    await waitFor(() => expect(screen.getByTestId('prompt-lines')).toHaveTextContent('PC-1'), { timeout: 5000 });
    expect(screen.getByTestId('prompt-lines')).toHaveTextContent('second line');
    expect((screen.getByLabelText('Command') as HTMLInputElement).disabled).toBe(false);
  });

  it('shows earlier commands with their answers, and Up recalls the last one', async () => {
    api.consoleHistory.mockResolvedValue(history({ lines: [line({ status: 'done', output: 'PC-1' }), line({ request_id: 'r2', command: 'whoami', status: 'done', output: 'nt authority\\system' })] }));
    render(<CommandPrompt deviceId="d1" hostname="PC-1" />);
    await userEvent.click(screen.getByRole('button', { name: 'Open command prompt' }));
    const box = (await screen.findByLabelText('Command')) as HTMLInputElement;
    expect(screen.getByTestId('prompt-lines')).toHaveTextContent('whoami');
    await userEvent.click(box);
    await userEvent.keyboard('{ArrowUp}');
    expect(box.value).toBe('whoami');
    await userEvent.keyboard('{ArrowUp}');
    expect(box.value).toBe('hostname');
  });

  it('says why when ScreenConnect has no record of the machine, and does not let a command be typed', async () => {
    api.consoleHistory.mockResolvedValue(history({ available: false, blocked: 'ScreenConnect has no record of this machine, so there is nothing to send a command to.' }));
    render(<CommandPrompt deviceId="d1" hostname="PC-1" />);
    await userEvent.click(screen.getByRole('button', { name: 'Open command prompt' }));
    expect(await screen.findByText(/no record of this machine/)).toBeTruthy();
    expect((screen.getByLabelText('Command') as HTMLInputElement).disabled).toBe(true);
  });

  it('shows the reason when a command is refused, and keeps what was typed', async () => {
    api.consoleSend.mockRejectedValue(new Error('A command for this machine is still waiting for an answer.'));
    render(<CommandPrompt deviceId="d1" hostname="PC-1" />);
    await userEvent.click(screen.getByRole('button', { name: 'Open command prompt' }));
    await userEvent.type(await screen.findByLabelText('Command'), 'dir{Enter}');
    expect(await screen.findByRole('alert')).toHaveTextContent('still waiting for an answer');
    expect((screen.getByLabelText('Command') as HTMLInputElement).value).toBe('dir');
  });

  it('a failed command prints its reason in red text', async () => {
    api.consoleHistory.mockResolvedValue(history({ lines: [line({ status: 'failed', output: 'ScreenConnect refused the command (403).' })] }));
    render(<CommandPrompt deviceId="d1" hostname="PC-1" />);
    await userEvent.click(screen.getByRole('button', { name: 'Open command prompt' }));
    expect(await screen.findByText('ScreenConnect refused the command (403).')).toBeTruthy();
    await act(async () => undefined);
  });
});
