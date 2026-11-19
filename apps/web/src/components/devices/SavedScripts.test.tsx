import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ list: vi.fn(), create: vi.fn(), patch: vi.fn(), remove: vi.fn(), run: vi.fn() }));
vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return { ...actual, savedScriptsApi: api };
});

import { SavedScripts } from './SavedScripts';

const reboot = { id: 's1', name: 'Reboot', command: 'shutdown /r /t 60', enabled: true };
const off = { id: 's2', name: 'Flush DNS', command: 'ipconfig /flushdns', enabled: false };

beforeEach(() => {
  Object.values(api).forEach((m) => m.mockReset());
  api.list.mockResolvedValue([reboot, off]);
  vi.spyOn(window, 'confirm').mockReturnValue(true);
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('SavedScripts', () => {
  it('offers only the scripts that are switched on and runs the picked one on this machine after a confirm', async () => {
    api.run.mockResolvedValue([{ device_id: 'd1', line: { request_id: 'r1' }, refused: null }]);
    const sent = vi.fn();
    render(<SavedScripts deviceId="d1" hostname="PC-1" onSent={sent} />);
    const select = await screen.findByLabelText('Saved script');
    expect(Array.from((select as HTMLSelectElement).options).map((o) => o.text)).toEqual(['Reboot']);
    await userEvent.click(screen.getByRole('button', { name: 'Run on this machine' }));
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('Reboot'));
    await waitFor(() => expect(api.run).toHaveBeenCalledWith('s1', ['d1']));
    expect(await screen.findByText(/Sent "Reboot"/)).toBeTruthy();
    expect(sent).toHaveBeenCalled();
  });

  it('sends nothing when the confirm is declined, and says why when the machine refuses', async () => {
    vi.spyOn(window, 'confirm').mockReturnValueOnce(false);
    render(<SavedScripts deviceId="d1" hostname="PC-1" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Run on this machine' }));
    expect(api.run).not.toHaveBeenCalled();
    api.run.mockResolvedValue([{ device_id: 'd1', line: null, refused: 'ScreenConnect has no record of this machine.' }]);
    await userEvent.click(screen.getByRole('button', { name: 'Run on this machine' }));
    expect(await screen.findByText(/Not sent: ScreenConnect has no record/)).toBeTruthy();
  });

  it('shows nothing at all to a person who may not see the scripts', async () => {
    api.list.mockRejectedValue(new Error('403'));
    render(<SavedScripts deviceId="d1" hostname="PC-1" />);
    await waitFor(() => expect(screen.getByTestId('saved-scripts')).toBeTruthy());
    expect(screen.getByText('none switched on')).toBeTruthy();
    expect(screen.queryByLabelText('Saved script')).toBeNull();
  });

  it('lets a manager add, switch on and delete scripts', async () => {
    api.create.mockResolvedValue({ id: 's3', name: 'GPU', command: 'gpupdate /force', enabled: true });
    api.patch.mockResolvedValue({ ...off, enabled: true });
    api.remove.mockResolvedValue(undefined);
    render(<SavedScripts deviceId="d1" hostname="PC-1" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Manage' }));
    await userEvent.type(screen.getByLabelText('Name'), 'GPU');
    await userEvent.type(screen.getByLabelText('Command'), 'gpupdate /force');
    await userEvent.click(screen.getByRole('button', { name: 'Save script' }));
    await waitFor(() => expect(api.create).toHaveBeenCalledWith({ name: 'GPU', command: 'gpupdate /force' }));
    await userEvent.click(screen.getByRole('button', { name: 'Switch on Flush DNS' }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith('s2', { enabled: true }));
    await userEvent.click(screen.getByRole('button', { name: 'Delete Reboot' }));
    await waitFor(() => expect(api.remove).toHaveBeenCalledWith('s1'));
  });
});
