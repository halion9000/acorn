import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';

const authFetch = vi.hoisted(() => vi.fn());
const listChildren = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));
vi.mock('@/lib/api', () => ({ msspApi: { listChildren } }));

import { QbrSecurity, clientIdFor, type Qbr } from './QbrSecurity';

const sample: Qbr = {
  client: 'Acme Dental',
  months: 3,
  from: '2026-08-20',
  to: '2026-11-18',
  highlights: ['10 alerts came in and 9 were handled (90%).'],
  security: {
    alerts_received: 10,
    alerts_received_by_severity: { critical: 1, high: 2, medium: 3, low: 4, info: 0 },
    alerts_handled: 9,
    alerts_open_now: 1,
    alerts_open_now_by_severity: { critical: 0, high: 1, medium: 0, low: 0, info: 0 },
    handled_percent: 90,
    vulnerabilities_open: 5,
    vulnerabilities_by_severity: { critical: 0, high: 2, medium: 3, low: 0, info: 0 },
    vulnerabilities_exploited: 0,
    devices: 42,
  },
  work: { cases_opened: 3, cases_closed: 2, alerts_resolved: 9 },
};

beforeEach(() => {
  authFetch.mockReset();
  listChildren.mockReset();
});
afterEach(() => cleanup());

describe('clientIdFor', () => {
  it('matches a client by name ignoring case and punctuation, and gives null for none or an empty name', () => {
    const kids = [{ id: 'a', name: 'Acme Dental, LLC' }, { id: 'b', name: 'Birch' }];
    expect(clientIdFor('acme dental llc', kids)).toBe('a');
    expect(clientIdFor('Cedar', kids)).toBeNull();
    expect(clientIdFor('', kids)).toBeNull();
  });
});

describe('QbrSecurity', () => {
  it('shows the highlights and numbers for the matching client and asks for that client and period', async () => {
    listChildren.mockResolvedValue([{ id: 'a', name: 'Acme Dental' }]);
    authFetch.mockResolvedValue({ ok: true, json: async () => sample });
    render(<QbrSecurity clientName="Acme Dental" months={3} />);
    expect(await screen.findByTestId('qbr-security')).toBeTruthy();
    expect(screen.getByText('10 alerts came in and 9 were handled (90%).')).toBeTruthy();
    expect(screen.getByText('90%')).toBeTruthy();
    expect(authFetch).toHaveBeenCalledWith('/api/v1/reports/qbr?client_id=a&months=3');
  });

  it('shows nothing when no client has that name, and nothing when the request fails', async () => {
    listChildren.mockResolvedValue([{ id: 'a', name: 'Birch' }]);
    const { container } = render(<QbrSecurity clientName="Acme Dental" months={3} />);
    await waitFor(() => expect(listChildren).toHaveBeenCalled());
    expect(authFetch).not.toHaveBeenCalled();
    expect(container.textContent).toBe('');
    listChildren.mockResolvedValue([{ id: 'a', name: 'Acme Dental' }]);
    authFetch.mockRejectedValue(new Error('down'));
    cleanup();
    const again = render(<QbrSecurity clientName="Acme Dental" months={3} />);
    await waitFor(() => expect(authFetch).toHaveBeenCalled());
    expect(again.container.textContent).toBe('');
  });
});
