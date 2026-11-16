import { describe, expect, it } from 'vitest';
import { buildDmarcRecord, fixList, nextStep, normalizePolicy } from '@/lib/dmarcAdvice';

describe('the DMARC record', () => {
  it('writes v and p first, leaves pct out at 100, and takes the reporting address with or without its tag', () => {
    expect(buildDmarcRecord({ policy: 'none' })).toBe('v=DMARC1; p=none');
    expect(buildDmarcRecord({ policy: 'quarantine', pct: 10, rua: 'rua=mailto:acme@reports.example.com' })).toBe('v=DMARC1; p=quarantine; pct=10; rua=mailto:acme@reports.example.com');
    expect(buildDmarcRecord({ policy: 'reject', pct: 100, rua: 'acme@reports.example.com' })).toBe('v=DMARC1; p=reject; rua=mailto:acme@reports.example.com');
    expect(buildDmarcRecord({ policy: 'reject', pct: 250 })).toBe('v=DMARC1; p=reject');
    expect(buildDmarcRecord({ policy: 'reject', pct: 0 })).toBe('v=DMARC1; p=reject; pct=1');
    expect(buildDmarcRecord({ policy: 'none', rua: '   ' })).toBe('v=DMARC1; p=none');
  });
  it('reads an odd published policy as monitor-only', () => {
    expect([normalizePolicy('Reject'), normalizePolicy(' quarantine '), normalizePolicy('none'), normalizePolicy('banana'), normalizePolicy(null)]).toEqual(['reject', 'quarantine', 'none', 'none', 'none']);
  });
});

describe('the next step', () => {
  const r = (policy: string, total: number, failed: number) => ({ policy, total, passed: total - failed, failed });
  it('waits until enough mail has been seen, and never moves a domain whose real mail is failing', () => {
    expect(nextStep(r('none', 40, 0))).toMatchObject({ change: false, policy: 'none', headline: 'Keep watching for now' });
    const bad = nextStep(r('none', 1000, 50));
    expect(bad).toMatchObject({ change: false, policy: 'none', headline: 'Fix the failing senders first' });
    expect(bad.reasons[0]).toContain('5% of 1,000');
    expect(nextStep(r('quarantine', 1000, 50)).change).toBe(false);
  });
  it('goes from monitoring to a tenth of mail quarantined, and from quarantine to reject only with a lot of clean mail', () => {
    expect(nextStep(r('none', 1000, 10))).toMatchObject({ change: true, policy: 'quarantine', pct: 10 });
    expect(nextStep(r('quarantine', 600, 3))).toMatchObject({ change: true, policy: 'reject', pct: 10 });
    expect(nextStep(r('quarantine', 300, 0))).toMatchObject({ change: false, headline: 'Stay on quarantine' });
    expect(nextStep(r('quarantine', 2000, 30))).toMatchObject({ change: false, headline: 'Stay on quarantine' });
    expect(nextStep(r('reject', 5000, 0))).toMatchObject({ change: false, headline: 'Already rejecting failing mail' });
  });
  it('a domain with no mail at all just keeps watching', () => {
    expect(nextStep(r('none', 0, 0)).headline).toBe('Keep watching for now');
  });
});

describe('the fix list', () => {
  const s = (ip: string, count: number, from: string, env: string, disposition = 'none') => ({ ip, count, header_from: from, envelope_from: env, disposition });
  it('groups by who the mail claims to be and its return path, biggest first, with the share of all failures', () => {
    const list = fixList([s('1.1.1.1', 30, 'acme.com', 'bounce.mailer.net'), s('1.1.1.2', 50, 'ACME.com', 'bounce.mailer.net', 'quarantine'), s('9.9.9.9', 20, 'acme.com', 'acme.com')]);
    expect(list).toHaveLength(2);
    expect(list[0]!.messages).toBe(80);
    expect(list[0]!.share).toBe(80);
    expect(list[0]!.text).toContain('80 messages from 2 addresses');
    expect(list[0]!.text).toContain('50 were already blocked');
    expect(list[0]!.text).toContain('sign its mail with DKIM for your domain');
    expect(list[1]!.text).toContain('add it to your SPF record');
  });
  it('lists at most five, and an empty list is empty', () => {
    expect(fixList(Array.from({ length: 9 }, (_, i) => s(`1.1.1.${i}`, 10 + i, `d${i}.com`, 'x.net')))).toHaveLength(5);
    expect(fixList([])).toEqual([]);
  });
  it('mail with no From or return path is still described', () => {
    expect(fixList([s('2.2.2.2', 5, '', '')])[0]!.text).toContain('mail with no visible From domain with no return path');
  });
});
