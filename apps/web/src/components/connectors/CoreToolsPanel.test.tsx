import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ coreTools: vi.fn() }));
vi.mock('@/lib/api', () => ({ connectorsApi: api }));

import { CoreToolsPanel } from './CoreToolsPanel';

const tool = (tool_id: string, title: string, connected: boolean, description = '') => ({ tool_id, title, description, connected, reported_at: '2026-10-26T12:00:00Z' });

function renderPanel() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
      <CoreToolsPanel />
    </SWRConfig>,
  );
}

describe('CoreToolsPanel', () => {
  beforeEach(() => api.coreTools.mockReset());

  it('lists each tool connected in CORE as connected, with its line, and says nothing is set up here', async () => {
    api.coreTools.mockResolvedValue([tool('huntress', 'Huntress', true, 'Managed EDR'), tool('petra-mdr', 'Petra MDR', true)]);
    renderPanel();
    const cards = await screen.findAllByTestId('core-tool');
    expect(cards).toHaveLength(2);
    expect(within(cards[0]).getByText('Huntress')).toBeInTheDocument();
    expect(within(cards[0]).getByText('Connected')).toBeInTheDocument();
    expect(within(cards[0]).getByText('Managed EDR')).toBeInTheDocument();
    expect(within(cards[0]).getByText('Managed in CORE')).toBeInTheDocument();
    expect(screen.getByText(/nothing to set up again/i)).toBeInTheDocument();
  });

  it('keeps tools CORE has not connected out of the connected cards, in a closed list with their count', async () => {
    api.coreTools.mockResolvedValue([tool('huntress', 'Huntress', true), tool('hudu', 'Hudu', false), tool('keeper', 'Keeper', false)]);
    renderPanel();
    expect(await screen.findAllByTestId('core-tool')).toHaveLength(1);
    expect(screen.getByText('2 tools in CORE not connected')).toBeInTheDocument();
    expect(screen.getAllByTestId('core-tool-idle').map((n) => n.textContent)).toEqual(['Hudu', 'Keeper']);
    expect(screen.getByText('Hudu').closest('details')).not.toHaveAttribute('open');
  });

  it('says so when CORE reported tools but none are connected', async () => {
    api.coreTools.mockResolvedValue([tool('hudu', 'Hudu', false)]);
    renderPanel();
    expect(await screen.findByText(/none of the tools in core are connected yet/i)).toBeInTheDocument();
    expect(screen.queryByTestId('core-tool')).toBeNull();
  });

  it('shows nothing before CORE has reported, and nothing when the list cannot be loaded', async () => {
    api.coreTools.mockResolvedValueOnce([]);
    const first = renderPanel();
    await waitFor(() => expect(api.coreTools).toHaveBeenCalled());
    expect(first.container).toBeEmptyDOMElement();
    first.unmount();
    api.coreTools.mockRejectedValueOnce(new Error('API 500'));
    const second = renderPanel();
    await waitFor(() => expect(api.coreTools).toHaveBeenCalledTimes(2));
    expect(second.container).toBeEmptyDOMElement();
  });
});
