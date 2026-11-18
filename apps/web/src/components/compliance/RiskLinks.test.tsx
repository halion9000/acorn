import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const api = vi.hoisted(() => ({ addLink: vi.fn(), removeLink: vi.fn() }));
const vendors = vi.hoisted(() => ({ list: vi.fn() }));
vi.mock('@/lib/api', () => ({ riskRegisterApi: api, vendorApi: vendors, apiErrorDetail: (e: unknown) => (e instanceof Error ? e.message : null) }));

import { RiskLinks, linkText } from './RiskLinks';

const control = { id: 'l1', kind: 'control' as const, framework: 'SOC2', ref: 'A1.3', label: 'Tests recovery plan procedures' };
const vendor = { id: 'l2', kind: 'vendor' as const, framework: null, ref: 'v1', label: 'Datto' };
const risk = (links = [control, vendor]) => ({ id: 'r1', links }) as never;

beforeEach(() => {
  api.addLink.mockReset();
  api.removeLink.mockReset();
  vendors.list.mockReset();
  vendors.list.mockResolvedValue({ vendors: [{ id: 'v1', name: 'Datto' }, { id: 'v2', name: 'Huntress' }] });
});

describe('linkText', () => {
  it('names a control by framework, id and title and a vendor by name, and says so when the vendor is gone', () => {
    expect(linkText(control)).toBe('Control: SOC 2 A1.3 Tests recovery plan procedures');
    expect(linkText(vendor)).toBe('Vendor: Datto');
    expect(linkText({ ...vendor, label: '' })).toBe('Vendor: a vendor that is no longer listed');
  });
});

describe('RiskLinks', () => {
  it('lists the links and removes one', async () => {
    const onChange = vi.fn();
    api.removeLink.mockResolvedValue(risk([vendor]));
    render(<RiskLinks clientId="c1" risk={risk()} archived={false} onChange={onChange} />);
    expect(screen.getByText('Control: SOC 2 A1.3 Tests recovery plan procedures')).toBeTruthy();
    await userEvent.click(screen.getByLabelText('Remove link: Vendor: Datto'));
    expect(api.removeLink).toHaveBeenCalledWith('c1', 'r1', 'l2');
    await waitFor(() => expect(onChange).toHaveBeenCalled());
  });

  it('adds a control by framework and id, and a vendor from the client list', async () => {
    const onChange = vi.fn();
    api.addLink.mockResolvedValue(risk());
    render(<RiskLinks clientId="c1" risk={risk([])} archived={false} onChange={onChange} />);
    expect(screen.getByText('Nothing linked yet.')).toBeTruthy();
    await userEvent.selectOptions(screen.getByLabelText('Framework'), 'HIPAA');
    await userEvent.type(screen.getByLabelText('Control id'), '164.312(d)');
    await userEvent.click(screen.getByText('Add link'));
    expect(api.addLink).toHaveBeenLastCalledWith('c1', 'r1', { kind: 'control', framework: 'HIPAA', ref: '164.312(d)' });
    await userEvent.selectOptions(screen.getByLabelText('Link kind'), 'vendor');
    await screen.findByText('Huntress');
    await userEvent.selectOptions(screen.getByLabelText('Vendor'), 'v2');
    await userEvent.click(screen.getByText('Add link'));
    expect(api.addLink).toHaveBeenLastCalledWith('c1', 'r1', { kind: 'vendor', ref: 'v2' });
  });

  it('shows the reason when the control is not one of the framework, and offers nothing on an archived risk', async () => {
    api.addLink.mockRejectedValue(new Error('That control is not in the list for that framework.'));
    const { rerender } = render(<RiskLinks clientId="c1" risk={risk([])} archived={false} onChange={vi.fn()} />);
    await userEvent.type(screen.getByLabelText('Control id'), 'ZZ9');
    await userEvent.click(screen.getByText('Add link'));
    expect((await screen.findByRole('alert')).textContent).toContain('not in the list');
    rerender(<RiskLinks clientId="c1" risk={risk()} archived={true} onChange={vi.fn()} />);
    expect(screen.queryByText('Add link')).toBeNull();
    expect(screen.queryByText('Remove')).toBeNull();
  });
});
