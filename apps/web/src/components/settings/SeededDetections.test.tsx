import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { SeededDetections, seededSentence } from './SeededDetections';

const authFetch = vi.fn();
vi.mock('@/lib/auth-session', () => ({ authFetch: (...a: unknown[]) => authFetch(...a) }));

beforeEach(() => {
  authFetch.mockReset();
});
afterEach(() => cleanup());

describe('seededSentence', () => {
  it('says the built-in rules, then the imported ones with each pack, with the Sigma prefix left off', () => {
    expect(
      seededSentence({ builtin: 118, imported: 77, packs: [{ name: 'Sigma: Linux', rules: 12 }, { name: 'Sigma: Windows', rules: 54 }] }),
    ).toBe('118 built-in rules; 77 imported Sigma rules in 2 rule packs (Linux 12, Windows 54).');
  });
  it('uses the singular, and says so when nothing is imported', () => {
    expect(seededSentence({ builtin: 1, imported: 1, packs: [{ name: 'Sigma: Cloud', rules: 1 }] })).toBe('1 built-in rule; 1 imported Sigma rule in 1 rule pack (Cloud 1).');
    expect(seededSentence({ builtin: 5, imported: 0, packs: [] })).toBe('5 built-in rules; no imported rule packs yet.');
  });
});

describe('SeededDetections', () => {
  it('shows the line with a link to the rules once the counts arrive', async () => {
    authFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ builtin: 10, imported: 3, packs: [{ name: 'Sigma: Windows', rules: 3 }] }) });
    render(<SeededDetections />);
    const line = await screen.findByTestId('seeded-detections');
    expect(line).toHaveTextContent('10 built-in rules; 3 imported Sigma rules in 1 rule pack (Windows 3).');
    expect(screen.getByRole('link', { name: 'Open Detection Rules' })).toHaveAttribute('href', '/detection');
    expect(authFetch).toHaveBeenCalledWith('/api/v1/rules/seeded-counts');
  });

  it('shows nothing when the counts cannot be read, whether refused or failing', async () => {
    authFetch.mockResolvedValue({ ok: false, status: 403, json: () => Promise.resolve({}) });
    const first = render(<SeededDetections />);
    await waitFor(() => expect(authFetch).toHaveBeenCalled());
    expect(screen.queryByTestId('seeded-detections')).toBeNull();
    first.unmount();
    authFetch.mockRejectedValue(new Error('network'));
    render(<SeededDetections />);
    await waitFor(() => expect(authFetch).toHaveBeenCalledTimes(2));
    expect(screen.queryByTestId('seeded-detections')).toBeNull();
  });
});
