import { render, screen } from '@testing-library/react';
import { SWRConfig } from 'swr';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DmarcNextStep } from './DmarcNextStep';

vi.mock('@/lib/auth-session', () => ({
  authFetch: vi.fn(async () => ({ ok: true, json: async () => ({ lines: [{ domain: 'Acme.com', client_dmarc_rua: 'rua=mailto:acme@reports.example.com' }] }) })),
}));

const wrap = (ui: React.ReactElement) => render(<SWRConfig value={{ provider: () => new Map() }}>{ui}</SWRConfig>);
const src = [{ ip: '1.1.1.1', count: 8, header_from: 'acme.com', envelope_from: 'bounce.mailer.net', disposition: 'none' }];

describe('What to do next (DMARC)', () => {
  beforeEach(() => vi.clearAllMocks());

  it('suggests the record with this domain’s reporting address and lists the senders to fix', async () => {
    wrap(<DmarcNextStep domain="acme.com" rollup={{ policy: 'none', total: 1000, passed: 990, failed: 10 }} sources={src} />);
    expect(screen.getByText('Move to quarantine for 10% of mail')).toBeInTheDocument();
    expect(await screen.findByText('v=DMARC1; p=quarantine; pct=10; rua=mailto:acme@reports.example.com')).toBeInTheDocument();
    expect(screen.getByText('_dmarc.acme.com')).toBeInTheDocument();
    expect(screen.getByTestId('dmarc-fixes').textContent).toContain('8 messages from 1 address');
  });

  it('shows no record when the domain should stay where it is, but still says why', () => {
    wrap(<DmarcNextStep domain="acme.com" rollup={{ policy: 'none', total: 30, passed: 30, failed: 0 }} sources={[]} />);
    expect(screen.getByText('Keep watching for now')).toBeInTheDocument();
    expect(screen.queryByTestId('dmarc-record')).toBeNull();
    expect(screen.queryByTestId('dmarc-fixes')).toBeNull();
  });
});
