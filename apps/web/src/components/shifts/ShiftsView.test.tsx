import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SWRConfig } from 'swr';

vi.mock('@/lib/api', () => ({
  shiftsApi: {
    handoffItems: async () => [
      { id: '1', priority: 'info', title: 'Disk free space low', type: 'alert', status: 'new', assigned_to: 'unassigned', notes: null },
      { id: '2', priority: 'weird', title: 'Odd severity', type: 'alert', status: 'new', assigned_to: 'unassigned', notes: null },
      { id: '3', priority: 'critical', title: 'RDP exposed', type: 'case', status: 'open', assigned_to: 'x', notes: null },
    ],
  },
}));

import { ShiftsView, handoffReport, priorityStyle } from './ShiftsView';

describe('ShiftsView', () => {
  it('renders info and unknown-severity alerts instead of crashing the page', async () => {
    render(
      <SWRConfig value={{ provider: () => new Map() }}>
        <ShiftsView />
      </SWRConfig>,
    );
    expect(await screen.findByText('Disk free space low')).toBeTruthy();
    expect(screen.getByText('Odd severity')).toBeTruthy();
    expect(screen.getByText('RDP exposed')).toBeTruthy();
  });

  it('has a style for any priority string', () => {
    expect(priorityStyle('info').label).toBe('Info');
    expect(priorityStyle('nonsense').label).toBe('Info');
    expect(priorityStyle('critical').label).toBe('Critical');
  });

  it('shows no invented analyst or shift hours, only counts of what is open, and links each item to its alert or case', async () => {
    render(
      <SWRConfig value={{ provider: () => new Map() }}>
        <ShiftsView />
      </SWRConfig>,
    );
    await screen.findByText('RDP exposed');
    expect(screen.queryByText('Alice Chen')).toBeNull();
    expect(screen.queryByText(/Analyst On Duty|Hours Remaining/)).toBeNull();
    const summary = screen.getByTestId('handoff-summary');
    expect(summary.textContent).toContain('Open items');
    expect(summary.textContent).toMatch(/3.*Open items/);
    expect(screen.getByRole('link', { name: '1' }).getAttribute('href')).toBe('/alerts/1');
    expect(screen.getByRole('link', { name: '3' }).getAttribute('href')).toBe('/cases/3');
  });

  it('writes the handoff report worst first with status and owner', () => {
    const text = handoffReport(
      [
        { id: 'a', priority: 'low', title: 'Minor', type: 'alert', status: 'new', assignedTo: 'unassigned', notes: '' },
        { id: 'b', priority: 'critical', title: 'Bad', type: 'case', status: 'open', assignedTo: 'sam', notes: 'call client' },
      ],
      new Date('2026-10-27T12:00:00Z'),
    );
    expect(text.indexOf('[CRITICAL]')).toBeLessThan(text.indexOf('[LOW]'));
    expect(text).toContain('2 open items');
    expect(text).toContain('assigned to: sam; notes: call client');
  });
});
