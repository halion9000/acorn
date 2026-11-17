import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const authFetch = vi.hoisted(() => vi.fn());
const reviewsList = vi.hoisted(() => vi.fn());
const auditsList = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));
vi.mock('@/lib/api', () => ({ accessReviewsApi: { list: reviewsList }, auditsApi: { list: auditsList } }));
vi.mock('@/components/mssp/ClientPicker', () => ({ ClientPicker: () => null, clientFromAddress: () => '' }));

import { ComplianceCalendar } from './ComplianceCalendar';

const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));
const audit = { audits: [{ id: 'a', name: 'SOC 2', framework: 'SOC2', auditor: null, period_end: '2027-01-31', status: 'fieldwork' }], frameworks: [] };

describe('Compliance calendar page', () => {
  beforeEach(() => {
    authFetch.mockReset();
    reviewsList.mockReset();
    auditsList.mockReset();
  });

  it('lists what falls due from all three sources, overdue first, each linking to its page', async () => {
    authFetch.mockImplementation(() => json([{ id: 'g1', kind: 'vendor', title: 'Vendor review: Pax8', owner: 'Hal', next_due: '2026-11-05' }, { id: 'g2', kind: 'policy', title: 'Acceptable use', owner: '', next_due: '2026-12-20' }]));
    reviewsList.mockResolvedValue({ reviews: [{ id: 'r', name: 'Q4 review', system: 'Microsoft 365', reviewer: 'Ann', due_date: '2026-12-01', status: 'open' }], systems: [] });
    auditsList.mockResolvedValue(audit);
    render(<ComplianceCalendar today="2026-11-16" />);
    const groups = await screen.findAllByTestId('calendar-group');
    expect(groups.map((g) => g.querySelector('h2')!.textContent)).toEqual(['Overdue', 'December 2026', 'January 2027']);
    expect(screen.getByRole('link', { name: 'Vendor review: Pax8' })).toHaveAttribute('href', '/compliance/vendors');
    expect(screen.getByRole('link', { name: 'Q4 review (Microsoft 365)' })).toHaveAttribute('href', '/compliance/access-reviews');
    expect(screen.getByRole('link', { name: 'SOC 2 (SOC2)' })).toHaveAttribute('href', '/compliance/audits');
  });

  it('a source that cannot be read leaves its entries out without hiding the others, and an empty calendar says so', async () => {
    authFetch.mockImplementation(() => json({}, 403));
    reviewsList.mockRejectedValue(new Error('403'));
    auditsList.mockResolvedValue(audit);
    const { unmount } = render(<ComplianceCalendar today="2026-11-16" />);
    await screen.findByRole('link', { name: 'SOC 2 (SOC2)' });
    unmount();
    auditsList.mockResolvedValue({ audits: [], frameworks: [] });
    render(<ComplianceCalendar today="2026-11-16" />);
    await waitFor(() => expect(screen.getByTestId('calendar-empty')).toBeInTheDocument());
  });
});
