import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const list = vi.hoisted(() => vi.fn());
const save = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api', () => ({ identitiesApi: { list } }));
vi.mock('@/lib/saveFile', () => ({ saveText: save }));

import { PrivilegedExport } from './PrivilegedExport';

const p = (email: string, mfa = 'covered') => ({ key: email, client_id: 'c', client_name: 'Acme', email, display_name: null, kind: 'member', enabled: true, admin: true, licensed: true, mfa, mfa_methods: null, signin_state: 'active', days_since_signin: 1, tools: ['m365'], sources: [], open_alerts: 0, top_severity: null });

describe('Download administrators', () => {
  beforeEach(() => {
    list.mockReset();
    save.mockReset();
  });

  it('reads every page of administrators for the chosen client and saves one CSV, riskiest first', async () => {
    list.mockImplementation(async ({ page }: { page: number }) => (page === 1 ? { items: [p('ok@acme.com')], pages: 2 } : { items: [p('bad@acme.com', 'none')], pages: 2 }));
    render(<PrivilegedExport clientId="c1" />);
    await userEvent.click(screen.getByRole('button', { name: 'Download administrators (CSV)' }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(list.mock.calls.map((c) => c[0])).toEqual([{ admin: true, clientId: 'c1', page: 1, pageSize: 200 }, { admin: true, clientId: 'c1', page: 2, pageSize: 200 }]);
    const [name, csv] = save.mock.calls[0] as [string, string];
    expect(name).toBe('privileged-accounts.csv');
    expect(csv.split('\r\n').slice(1, 3).map((l) => l.split(',')[1])).toEqual(['bad@acme.com', 'ok@acme.com']);
  });

  it('says what went wrong and saves nothing when the list cannot be read', async () => {
    list.mockRejectedValue(new Error('API 500'));
    render(<PrivilegedExport clientId="" />);
    await userEvent.click(screen.getByRole('button', { name: 'Download administrators (CSV)' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('API 500');
    expect(save).not.toHaveBeenCalled();
    expect(list.mock.calls[0]![0].clientId).toBeUndefined();
  });
});
