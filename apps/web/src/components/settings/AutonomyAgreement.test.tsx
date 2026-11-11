import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('@/lib/api', async (original) => ({ ...(await original<typeof import('@/lib/api')>()), approvalAgreementApi: { get: api.get } }));

import { AutonomyAgreement } from './AutonomyAgreement';

const show = () => render(<SWRConfig value={{ provider: () => new Map() }}><AutonomyAgreement /></SWRConfig>);

beforeEach(() => {
  api.get.mockReset();
});

describe('AutonomyAgreement', () => {
  it('lists each kind of action with its counts, agreement share and suggestion in words', async () => {
    api.get.mockResolvedValue({
      window_days: 90,
      rules: 'Decided = approved + denied + expired.',
      rows: [
        { action: 'isolate_host', proposed: 25, approved: 24, denied: 1, expired: 0, pending: 0, decided: 25, agreement: 0.96, suggestion: 'promote' },
        { action: 'block_ip', proposed: 3, approved: 0, denied: 0, expired: 0, pending: 3, decided: 0, agreement: null, suggestion: 'too few' },
      ],
    });
    show();
    const row = await screen.findByTestId('agreement-isolate_host');
    expect(row).toHaveTextContent('96%');
    expect(row).toHaveTextContent('Could act more on its own');
    expect(screen.getByTestId('agreement-block_ip')).toHaveTextContent('—');
    expect(screen.getByTestId('agreement-block_ip')).toHaveTextContent('Too few decisions to say');
    expect(screen.getByTestId('agreement')).toHaveTextContent('Decided = approved + denied + expired.');
  });

  it('says so when nothing was asked', async () => {
    api.get.mockResolvedValue({ window_days: 90, rules: 'r', rows: [] });
    show();
    expect(await screen.findByTestId('agreement-empty')).toBeInTheDocument();
  });
});
