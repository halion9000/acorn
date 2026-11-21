import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), setPublic: vi.fn() }));
vi.mock('@/lib/api', () => ({ apiErrorDetail: (e: unknown) => (e instanceof Error ? e.message : null), trustCenterApi: api, msspApi: { listChildren: async () => [] } }));

import { TrustCenterView } from './TrustCenterView';

const center = (over: Record<string, unknown> = {}) => ({
  enabled: true, headline: 'Security at Acme', about: 'We take it seriously.', contact_email: 'security@acme.com', documents: [{ name: 'SOC 2 report', url: 'https://acme.example/soc2.pdf' }],
  frameworks: [{ framework: 'SOC2', controls: 60, healthy: 45, percent_healthy: 75 }], policies: [{ id: 'p1', title: 'Acceptable use', last_reviewed_at: '2026-10-01' }], updated_at: '2026-11-14T10:00:00Z', updated_by: 'hal@goliveoak.com',
  available_frameworks: ['SOC2', 'HIPAA'], available_policies: [{ id: 'p1', title: 'Acceptable use' }, { id: 'p2', title: 'Access control' }], chosen_frameworks: ['SOC2'], chosen_policy_ids: ['p1'], ...over,
});

beforeEach(() => {
  api.get.mockReset();
  api.put.mockReset();
  api.setPublic.mockReset();
  api.get.mockResolvedValue(center());
  window.history.replaceState(null, '', '/compliance/trust-center');
});

describe('TrustCenterView', () => {
  it('shows the page as a customer would read it: the headline, the health of each chosen framework as it is now, the policies and the documents', async () => {
    render(<TrustCenterView />);
    const preview = await screen.findByTestId('trust-preview');
    expect(preview).toHaveTextContent('Security at Acme');
    expect(screen.getByTestId('trust-frameworks')).toHaveTextContent('75% of 60 controls healthy');
    expect(screen.getByTestId('trust-policies')).toHaveTextContent('Acceptable use');
    expect(screen.getByTestId('trust-policies')).toHaveTextContent('reviewed 2026-10-01');
    expect(within(screen.getByTestId('trust-documents')).getByRole('link', { name: 'SOC 2 report' })).toHaveAttribute('href', 'https://acme.example/soc2.pdf');
    expect(preview).toHaveTextContent('security@acme.com');
  });

  it('says when it is not switched on and when no controls are tested yet', async () => {
    api.get.mockResolvedValue(center({ enabled: false, frameworks: [{ framework: 'SOC2', controls: 60, healthy: 0, percent_healthy: 0 }], policies: [], documents: [] }));
    render(<TrustCenterView />);
    expect(await screen.findByTestId('trust-preview')).toHaveTextContent('(not switched on)');
    api.get.mockResolvedValue(center({ frameworks: [{ framework: 'HIPAA', controls: 0, healthy: 0, percent_healthy: null }] }));
  });

  it('saves what was chosen: the switch, the text, the frameworks, the policies and the documents', async () => {
    api.put.mockResolvedValue(center());
    render(<TrustCenterView />);
    const editor = await screen.findByTestId('trust-editor');
    await userEvent.click(within(editor).getByLabelText('Show HIPAA'));
    await userEvent.click(within(editor).getByLabelText('List Access control'));
    await userEvent.type(within(editor).getByLabelText('Document name'), 'Pen test summary');
    await userEvent.type(within(editor).getByLabelText('Document link'), 'https://acme.example/pt.pdf');
    await userEvent.click(within(editor).getByRole('button', { name: 'Add document' }));
    await userEvent.click(within(editor).getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith('', {
        enabled: true, headline: 'Security at Acme', about: 'We take it seriously.', contact_email: 'security@acme.com', frameworks: ['SOC2', 'HIPAA'], policy_ids: ['p1', 'p2'],
        documents: [{ name: 'SOC 2 report', url: 'https://acme.example/soc2.pdf' }, { name: 'Pen test summary', url: 'https://acme.example/pt.pdf' }],
      }),
    );
    expect(await within(editor).findByText('Saved.')).toBeTruthy();
  });

  it('says to turn a framework on when none is, and shows the reason when saving is refused', async () => {
    api.get.mockResolvedValue(center({ available_frameworks: [], chosen_frameworks: [], frameworks: [] }));
    api.put.mockRejectedValue(new Error('The link for Oops must start with https://'));
    render(<TrustCenterView />);
    const editor = await screen.findByTestId('trust-editor');
    expect(editor).toHaveTextContent('No framework is turned on');
    await userEvent.click(within(editor).getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('must start with https://');
  });
});

describe('printing the trust center', () => {
  it('offers Print or save as PDF once loaded, and prints through the browser', async () => {
    const print = vi.spyOn(window, 'print').mockImplementation(() => {});
    render(<TrustCenterView />);
    await userEvent.click(await screen.findByRole('button', { name: 'Print or save as PDF' }));
    expect(print).toHaveBeenCalledTimes(1);
    print.mockRestore();
  });

  it('leaves the editor and the page heading off the paper, so only what a customer sees is printed', async () => {
    render(<TrustCenterView />);
    expect(await screen.findByTestId('trust-editor')).toHaveClass('print:hidden');
    expect(screen.getByRole('heading', { name: 'Trust center' }).parentElement).toHaveClass('print:hidden');
    expect(screen.getByTestId('trust-preview')).not.toHaveClass('print:hidden');
  });
});

describe('the public link', () => {
  it('is off until switched on, then shows the path and can make a new link or be switched off again', async () => {
    api.get.mockResolvedValue(center({ public_enabled: false, public_path: null }));
    render(<TrustCenterView />);
    const panel = await screen.findByTestId('public-link');
    expect(panel).toHaveTextContent('Public link (off)');
    expect(within(panel).queryByTestId('public-path')).toBeNull();
    api.setPublic.mockResolvedValue(center({ public_enabled: true, public_path: '/api/v1/public/trust/abc123' }));
    await userEvent.click(within(panel).getByRole('button', { name: 'Switch the public link on' }));
    expect(api.setPublic).toHaveBeenLastCalledWith('', { enabled: true });
    expect(await screen.findByTestId('public-path')).toHaveTextContent('/api/v1/public/trust/abc123');
    api.setPublic.mockResolvedValue(center({ public_enabled: true, public_path: '/api/v1/public/trust/new456' }));
    await userEvent.click(screen.getByRole('button', { name: 'Make a new link' }));
    expect(api.setPublic).toHaveBeenLastCalledWith('', { enabled: true, new_link: true });
    expect(await screen.findByText('/api/v1/public/trust/new456')).toBeInTheDocument();
    api.setPublic.mockResolvedValue(center({ public_enabled: false, public_path: '/api/v1/public/trust/new456' }));
    await userEvent.click(screen.getByRole('button', { name: 'Switch the public link off' }));
    expect(api.setPublic).toHaveBeenLastCalledWith('', { enabled: false });
  });
});
