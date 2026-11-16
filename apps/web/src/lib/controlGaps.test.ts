import { describe, expect, it } from 'vitest';
import type { ControlRowT } from '@/lib/api';
import { gapCsv, gapReport } from '@/lib/controlGaps';

const row = (framework: string, id: string, accepted: number, owner?: string | null, title = `Title ${id}`): ControlRowT => ({
  framework, control_id: id, title, group: 'Access', state: 'not_tested', accepted, pending: 0, rejected: 0, newest_evidence: null, age_days: null, link: '', owner,
});

describe('the gap report', () => {
  const rows = [row('SOC2', 'CC1', 0), row('SOC2', 'CC2', 3, 'Ann'), row('SOC2', 'CC3', 0, 'Bob'), row('SOC2', 'CC4', 2, '  '), row('ISO27001', 'A1', 0, null), row('ISO27001', 'A2', 0, 'Cy'), row('ISO27001', 'A3', 0)];

  it('counts missing evidence, missing owners and both, per framework, the worst framework first', () => {
    const r = gapReport(rows);
    expect(r.map((g) => [g.framework, g.total, g.noEvidence, g.noOwner, g.bothMissing.map((c) => c.control_id)])).toEqual([
      ['ISO27001', 3, 3, 2, ['A1', 'A3']],
      ['SOC2', 4, 2, 2, ['CC1']],
    ]);
  });

  it('a blank owner counts as no owner, and a control with only one thing missing is not a gap of both', () => {
    const r = gapReport([row('SOC2', 'X', 1, ' '), row('SOC2', 'Y', 0, 'Dee')]);
    expect(r[0]).toMatchObject({ noOwner: 1, noEvidence: 1 });
    expect(r[0]!.bothMissing).toEqual([]);
  });

  it('writes the CSV with quoting and a safe formula start, and an empty report is only the header', () => {
    expect(gapCsv([])).toBe('framework,control,title,group,health\r\n');
    const csv = gapCsv(gapReport([row('SOC2', 'CC1', 0, null, '=cmd, "x"')]));
    expect(csv.split('\r\n')[1]).toBe('SOC2,CC1,"\'=cmd, ""x""",Access,not_tested');
  });
});
