import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';

import { SenderDetailPanel, trendPercent, trendWords, type DmarcSender } from './DmarcView';

const week = (w: string, messages: number, failed: number, spf = 0, dkim = 0) => ({ week: w, messages, failed, spf_failed: spf, dkim_failed: dkim });

describe('how a sender is heading', () => {
  it('words the share of failed mail, and says rising, falling or steady', () => {
    expect(trendPercent(25, 100)).toBe('25%');
    expect(trendPercent(0, 0)).toBe('0%');
    expect(trendWords([week('a', 100, 2), week('b', 100, 40)])).toBe('Failures are rising: 2% at first, 40% now.');
    expect(trendWords([week('a', 100, 40), week('b', 100, 3)])).toBe('Failures are falling: 40% at first, 3% now.');
    expect(trendWords([week('a', 100, 10), week('b', 100, 12)])).toBe('Failures are steady: 10% at first, 12% now.');
    expect(trendWords([week('a', 100, 10)])).toBe('');
    expect(trendWords([])).toBe('');
  });
});

const sender = (trend: ReturnType<typeof week>[] | undefined): DmarcSender =>
  ({
    name: 'SendGrid',
    identified: true,
    emails: 200,
    passed: 150,
    failed: 50,
    status: 'warning',
    detail: { spf_domains: ['sendgrid.net'], dkim_domains: ['acme.com'], envelope_from: [], header_from: ['acme.com'], causes: [], spf_only_failed: 0, dkim_only_failed: 50, both_failed: 0, dispositions: { none: 200 }, reasons: [], addresses: ['167.89.1.1'], trend },
  }) as unknown as DmarcSender;

describe('the sender detail', () => {
  it('shows each week with its messages and failures, marks the weeks that failed, and says where it is heading', () => {
    render(<SenderDetailPanel sender={sender([week('2026-11-02', 100, 0), week('2026-11-09', 100, 50, 0, 50)])} />);
    const trend = screen.getByTestId('sender-trend');
    const rows = within(trend).getAllByRole('row');
    expect(rows).toHaveLength(3);
    expect(rows[1]).toHaveTextContent('2026-11-02');
    expect(rows[2]).toHaveTextContent('50 (50%)');
    expect(trend).toHaveTextContent('Failures are rising: 0% at first, 50% now.');
  });

  it('shows no history from an older server or with only one week', () => {
    const { unmount } = render(<SenderDetailPanel sender={sender(undefined)} />);
    expect(screen.queryByTestId('sender-trend')).toBeNull();
    unmount();
    render(<SenderDetailPanel sender={sender([week('2026-11-02', 100, 0)])} />);
    expect(screen.queryByTestId('sender-trend')).toBeNull();
  });
});
