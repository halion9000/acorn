import { describe, expect, it } from 'vitest';
import { healthReport, healthReportFileName, scrubbed } from './healthReport';

const NOW = new Date('2026-11-10T22:30:00Z');

describe('healthReport', () => {
  it('is readable JSON holding the snapshot, when it was made, and a plain note', () => {
    const snapshot = { overall: 'degraded', down: ['fusion'], services: [{ service: 'fusion', status: 'down', latency_ms: 3000, detail: 'timed out' }], runtime: { version: { commit: 'd63d31a2', up_seconds: 900 } } };
    const parsed = JSON.parse(healthReport(snapshot, NOW));
    expect(parsed).toEqual({ report: 'A.C.O.R.N platform health', made: '2026-11-10T22:30:00.000Z', note: 'No passwords, keys or tokens are included.', snapshot });
    expect(healthReport(snapshot, NOW)).toContain('\n  "made"');
  });

  it('blanks text under a secret-looking field name at any depth, and leaves names, numbers and flags alone', () => {
    const out = scrubbed({
      microsoft_secret: { expires: '2027-01-01', days_left: 52, value: 'abc123' },
      old_credentials: [{ name: 'Graph app', age_days: 400 }],
      services: [{ service: 'api', api_key: 'sk-live-1', healthy: true }],
      plain: 'kept',
      password: '',
    }) as Record<string, unknown>;
    expect(out.microsoft_secret).toEqual({ expires: '2027-01-01', days_left: 52, value: '[removed]' });
    expect(out.old_credentials).toEqual([{ name: 'Graph app', age_days: 400 }]);
    expect(out.services).toEqual([{ service: 'api', api_key: '[removed]', healthy: true }]);
    expect(out.plain).toBe('kept');
    expect(out.password).toBe('');
    expect(JSON.stringify(out)).not.toContain('sk-live-1');
  });

  it('keeps the expiry date, kind and name of a credential readable but never its value, key or token', () => {
    const out = scrubbed({
      old_credentials: [{ kind: 'API key Reports', age_days: 400, key: 'sk-live-9', token: 'tok-9' }],
      microsoft_secret: { expires_on: '2026-12-01', days_left: 20, secret: 'hunter2' },
    });
    expect(out).toEqual({
      old_credentials: [{ kind: 'API key Reports', age_days: 400, key: '[removed]', token: '[removed]' }],
      microsoft_secret: { expires_on: '2026-12-01', days_left: 20, secret: '[removed]' },
    });
    expect(JSON.stringify(out)).not.toMatch(/sk-live-9|tok-9|hunter2/);
  });

  it('names the file by the minute it was made', () => {
    expect(healthReportFileName(NOW)).toBe('acorn-health-2026-11-10-22-30.json');
  });
});
