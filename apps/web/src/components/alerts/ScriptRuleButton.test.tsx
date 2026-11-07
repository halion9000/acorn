import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ make: vi.fn(), scriptOptions: vi.fn(), toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock('@/lib/api', () => ({ alertsApi: { scriptOptions: api.scriptOptions }, scriptRulesApi: { make: api.make } }));
vi.mock('react-hot-toast', () => ({ default: api.toast }));

import { ScriptRuleButton } from './ScriptRuleButton';

const options = { scripts: [{ id: 101, name: 'Remove rogue ScreenConnect (Windows)', one_click: false }, { id: 102, name: 'Remove rogue ScreenConnect (Mac)', one_click: true }], tickets: [] };
const renderIt = () =>
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <ScriptRuleButton alertId="a1" clientName="Acme" />
    </SWRConfig>,
  );

beforeEach(() => {
  api.make.mockReset().mockResolvedValue({ id: 'r1', queued_now: 1 });
  api.scriptOptions.mockReset().mockResolvedValue(options);
  api.toast.error.mockReset();
  api.toast.success.mockReset();
});

describe('Auto-run script', () => {
  it('cannot be made until a script is chosen, and says for each script whether CORE asks first', async () => {
    const user = userEvent.setup();
    renderIt();
    await user.click(screen.getByRole('button', { name: 'Auto-run script' }));
    const make = await screen.findByRole('button', { name: 'Make the rule' });
    expect(make).toBeDisabled();
    await user.selectOptions(await screen.findByLabelText('Windows script'), '101');
    expect(screen.getByText(/asks for your approval in CORE first/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Mac script'), '102');
    expect(screen.getByText(/runs at once/)).toBeInTheDocument();
    expect(make).toBeEnabled();
  });

  it('sends the scripts, the condition and the place, and says how many requests went to CORE', async () => {
    const user = userEvent.setup();
    renderIt();
    await user.click(screen.getByRole('button', { name: 'Auto-run script' }));
    await user.selectOptions(await screen.findByLabelText('Windows script'), '101');
    await user.selectOptions(screen.getByLabelText('Mac script'), '102');
    await user.selectOptions(screen.getByLabelText('Only when the client already uses'), 'screenconnect');
    await user.click(screen.getByLabelText('for every client'));
    await user.click(screen.getByRole('button', { name: 'Make the rule' }));
    await waitFor(() => expect(api.make).toHaveBeenCalledWith({ alert_id: 'a1', scope: 'all', windows_script_id: 101, mac_script_id: 102, requires_tool: 'screenconnect' }));
    expect(api.toast.success).toHaveBeenCalledWith(expect.stringContaining('1 script request is on its way to CORE'));
    expect(screen.getByRole('button', { name: 'Auto-run script: on' })).toBeInTheDocument();
  });

  it('sends only the script that was chosen, and shows the reason when it is refused', async () => {
    api.make.mockRejectedValue(new Error('There is already a script rule for this type of alert here.'));
    const user = userEvent.setup();
    renderIt();
    await user.click(screen.getByRole('button', { name: 'Auto-run script' }));
    await user.selectOptions(await screen.findByLabelText('Mac script'), '102');
    await user.click(screen.getByRole('button', { name: 'Make the rule' }));
    await waitFor(() => expect(api.make).toHaveBeenCalledWith({ alert_id: 'a1', scope: 'client', windows_script_id: undefined, mac_script_id: 102, requires_tool: undefined }));
    expect(api.toast.error).toHaveBeenCalledWith('There is already a script rule for this type of alert here.');
  });

  it('says so when CORE has no script switched on', async () => {
    api.scriptOptions.mockResolvedValue({ scripts: [], tickets: [] });
    const user = userEvent.setup();
    renderIt();
    await user.click(screen.getByRole('button', { name: 'Auto-run script' }));
    expect(await screen.findByText(/has not switched any script on/)).toBeInTheDocument();
  });
});
