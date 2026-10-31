/**
 * Settings has ONE place for the tools connected to A.C.O.R.N: the Connectors page. A second "Integrations" tab used to list the same connectors with a smaller copy of the same controls
 * (the sync-then-test behaviour of its Test button is covered in ConnectorsView.test.tsx).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ syncNow: vi.fn(), test: vi.fn() }));
const swrMutate = vi.hoisted(() => vi.fn());
const connectors = vi.hoisted(() => [
  { id: 'c1', name: 'NinjaOne', type: 'core_feed', status: 'active', description: '' },
  { id: 'c2', name: 'Splunk', type: 'splunk', status: 'active', description: '' },
]);
vi.mock('swr', () => ({
  __esModule: true,
  default: (key: string) => ({ data: key === 'settings:connectors' ? { connectors } : undefined, error: undefined, isLoading: false, mutate: swrMutate }),
}));
vi.mock('@/lib/api', () => ({
  __esModule: true,
  apiKeysApi: { list: vi.fn(), create: vi.fn(), revoke: vi.fn() },
  deploymentApi: { getAirgapStatus: vi.fn(), getLlmStatus: vi.fn(), getLlmCredential: vi.fn(), upsertLlmCredential: vi.fn(), deleteLlmCredential: vi.fn() },
  connectorsApi: { list: vi.fn(), statuses: vi.fn(), syncNow: api.syncNow, test: api.test },
  authApi: { currentUser: () => ({ id: 'u1', email: 'a@b.com', account_name: 'a', role: 'admin', tenant_id: 't1' }), updateUserPreferences: vi.fn() },
  tenantsApi: { details: vi.fn(), users: vi.fn() },
  ApiError: class ApiError extends Error {},
}));
const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock('react-hot-toast', () => ({ __esModule: true, default: toast }));

import { SettingsView } from './SettingsView';

beforeEach(() => {
  api.syncNow.mockReset();
  api.test.mockReset();
  swrMutate.mockReset();
  toast.success.mockReset();
  api.test.mockResolvedValue({ success: true, latencyMs: 12 });
});

describe('Settings: one place for connected tools', () => {
  it('has no separate Integrations tab', async () => {
    render(<SettingsView />);
    await screen.findByRole('navigation', { name: 'Settings sections' });
    expect(screen.queryByRole('button', { name: /^integrations/i })).toBeNull();
    expect(screen.queryByText('Connected log sources, EDRs, identity providers.')).toBeNull();
  });

  it('still lists the Connectors page, where the tools are managed', async () => {
    render(<SettingsView />);
    const link = await screen.findByRole('link', { name: /connectors/i });
    expect(link).toHaveAttribute('href', '/settings/connectors');
  });
});
