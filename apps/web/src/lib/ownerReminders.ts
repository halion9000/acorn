/**
 * Evidence reminders by owner: the controls that still need evidence (not tested, at risk because the evidence is old or only pending, or unhealthy because some was rejected), grouped by who owns
 * them, each group with a short message that can be pasted to that person. Controls with no owner are gathered last so they are not forgotten. Pure over the control list the Controls page holds.
 */
import type { ControlRowT } from '@/lib/api';

export interface OwnerGroup {
  /** The owner's name as typed; "" for controls nobody owns. */
  owner: string;
  controls: ControlRowT[];
}

const NEEDS: ControlRowT['state'][] = ['unhealthy', 'at_risk', 'not_tested'];
const REASON: Record<string, string> = {
  unhealthy: 'some evidence was rejected',
  at_risk: 'its evidence is old or still waiting to be accepted',
  not_tested: 'no evidence yet',
};
const rank = (s: ControlRowT['state']): number => NEEDS.indexOf(s);

/** The controls that need evidence, grouped by owner (names compared ignoring case and spaces, listed by most controls first, then name), the unowned group last (pure). */
export function ownerGroups(rows: ControlRowT[]): OwnerGroup[] {
  const by = new Map<string, OwnerGroup>();
  for (const r of rows) {
    if (!NEEDS.includes(r.state)) continue;
    const owner = (r.owner ?? '').trim();
    const key = owner.toLowerCase().replace(/\s+/g, ' ');
    const g = by.get(key) ?? { owner: owner.replace(/\s+/g, ' '), controls: [] };
    g.controls.push(r);
    by.set(key, g);
  }
  const groups = [...by.values()];
  for (const g of groups) g.controls.sort((a, b) => rank(a.state) - rank(b.state) || a.framework.localeCompare(b.framework) || a.control_id.localeCompare(b.control_id, undefined, { numeric: true }));
  return groups.sort((a, b) => (a.owner === '') !== (b.owner === '') ? (a.owner === '' ? 1 : -1) : b.controls.length - a.controls.length || a.owner.localeCompare(b.owner));
}

/** A message for one owner: how many controls, and each with why it needs evidence (pure). */
export function reminderText(g: OwnerGroup, today: string): string {
  const n = g.controls.length;
  const lines = g.controls.map((c) => `- ${c.framework} ${c.control_id} ${c.title}: ${REASON[c.state] ?? c.state}`);
  const hello = g.owner ? `Hi ${g.owner},` : 'Hello,';
  return [`${hello} as of ${today}, ${n} control${n === 1 ? '' : 's'} ${g.owner ? 'you own' : 'nobody owns'} ${n === 1 ? 'needs' : 'need'} evidence:`, ...lines, '', 'Please add the evidence in A.C.O.R.N under Compliance, Controls (Add evidence), or tell me if the control does not apply.'].join('\n');
}
