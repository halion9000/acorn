import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const overlap = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api', () => ({ complianceDashboardApi: { overlap } }));

import { FrameworkOverlap, byFrameworkText } from './FrameworkOverlap';

const row = (over: Record<string, unknown> = {}) => ({
  framework: 'PCI-DSS',
  name: 'PCI DSS',
  total_controls: 75,
  overlapping_controls: 31,
  unmapped_controls: 44,
  percent_overlapping: 41,
  shared_topics: ['Strong authentication and multi-factor', 'Backups and recovery'],
  new_topics: ['Physical access to facilities'],
  by_framework: { 'NIST CSF': 30, 'CIS IG1': 28 },
  ...over,
});

beforeEach(() => overlap.mockReset());
afterEach(() => cleanup());

describe('FrameworkOverlap', () => {
  it('shows how many controls of each framework that is off the ones that are on already cover, and its topics on request', async () => {
    overlap.mockResolvedValue({ enabled: ['NIST-CSF'], candidates: [row()] });
    render(<FrameworkOverlap clientId="c1" />);
    expect(await screen.findByText('PCI DSS')).toBeTruthy();
    expect(overlap).toHaveBeenCalledWith('c1');
    expect(screen.getByTestId('overlap-row').textContent).toContain('31 overlapping controls (41%)');
    expect(screen.getByText('30 with NIST CSF, 28 with CIS IG1')).toBeTruthy();
    expect(screen.getByText('44 controls are not mapped yet, so their overlap is not known.')).toBeTruthy();
    expect(screen.queryByText(/Already covered/)).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Show topics' }));
    expect(screen.getByText(/Already covered: Strong authentication and multi-factor, Backups and recovery/)).toBeTruthy();
    expect(screen.getByText(/New work: Physical access to facilities/)).toBeTruthy();
  });

  it('asks for a framework to be turned on first when none is', async () => {
    overlap.mockResolvedValue({ enabled: [], candidates: [row({ overlapping_controls: 0, percent_overlapping: 0, by_framework: {}, shared_topics: [] })] });
    render(<FrameworkOverlap clientId="" />);
    expect(await screen.findByText(/Turn a framework on first/)).toBeTruthy();
    expect(screen.getByTestId('overlap-row').textContent).toContain('0 overlapping controls');
  });

  it('shows nothing when there is no framework left to add', async () => {
    overlap.mockResolvedValue({ enabled: ['SOC2', 'ISO27001', 'NIST-CSF', 'PCI-DSS', 'HIPAA', 'CIS-IG1'], candidates: [] });
    render(<FrameworkOverlap clientId="" />);
    await waitFor(() => expect(overlap).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId('framework-overlap')).toBeNull();
  });
});

describe('byFrameworkText', () => {
  it('lists the biggest share first', () => {
    expect(byFrameworkText({ A: 1, B: 5 })).toBe('5 with B, 1 with A');
    expect(byFrameworkText({})).toBe('');
  });
});
