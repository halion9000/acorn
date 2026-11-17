import { describe, expect, it } from 'vitest';
import type { ControlRowT } from '@/lib/api';
import { ownerGroups, reminderText } from '@/lib/ownerReminders';

const row = (control_id: string, state: ControlRowT['state'], owner: string | null, framework = 'SOC2', title = `Title ${control_id}`): ControlRowT => ({
  framework, control_id, title, group: 'G', state, accepted: 0, pending: 0, rejected: 0, newest_evidence: null, age_days: null, link: '', owner,
});

describe('evidence reminders by owner', () => {
  const rows = [row('CC1.1', 'not_tested', 'Ann'), row('CC1.2', 'healthy', 'Ann'), row('CC2.1', 'unhealthy', ' ann '), row('CC3.1', 'at_risk', 'Bob'), row('CC9.1', 'not_tested', null), row('CC9.2', 'not_tested', ''), row('CC4.1', 'not_tested', 'Bob'), row('CC4.2', 'not_tested', 'Bob')];

  it('groups the controls that need evidence by owner, ignoring case and spaces, biggest group first, the unowned last, and leaves healthy ones out', () => {
    const g = ownerGroups(rows);
    expect(g.map((x) => [x.owner, x.controls.map((c) => c.control_id)])).toEqual([
      ['Bob', ['CC3.1', 'CC4.1', 'CC4.2']],
      ['Ann', ['CC2.1', 'CC1.1']],
      ['', ['CC9.1', 'CC9.2']],
    ]);
  });

  it('puts the worst states first inside a group and sorts control ids by their numbers', () => {
    const g = ownerGroups([row('CC10.1', 'not_tested', 'Ann'), row('CC2.1', 'not_tested', 'Ann'), row('CC5.1', 'unhealthy', 'Ann')]);
    expect(g[0]!.controls.map((c) => c.control_id)).toEqual(['CC5.1', 'CC2.1', 'CC10.1']);
  });

  it('writes a message that names each control and why, and one for controls nobody owns', () => {
    const [bob] = ownerGroups(rows);
    const text = reminderText(bob!, '2026-11-16');
    expect(text).toContain('Hi Bob, as of 2026-11-16, 3 controls you own need evidence:');
    expect(text).toContain('- SOC2 CC3.1 Title CC3.1: its evidence is old or still waiting to be accepted');
    expect(text).toContain('- SOC2 CC4.1 Title CC4.1: no evidence yet');
    const unowned = ownerGroups(rows).at(-1)!;
    expect(reminderText(unowned, '2026-11-16')).toMatch(/^Hello, as of 2026-11-16, 2 controls nobody owns need evidence:/);
    expect(reminderText({ owner: 'Cy', controls: [row('A', 'not_tested', 'Cy')] }, 'd')).toContain('1 control you own needs evidence');
  });

  it('is empty when every control is healthy', () => {
    expect(ownerGroups([row('A', 'healthy', 'Ann')])).toEqual([]);
    expect(ownerGroups([])).toEqual([]);
  });
});
