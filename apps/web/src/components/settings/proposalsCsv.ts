import { csvText } from '@/lib/csv';
import type { AgentProposal } from '@/lib/api';

const RUNG: Record<AgentProposal['rung'], string> = {
  shadow: 'Would have done (shadow)',
  suggest: 'Suggested',
  ask: 'Asked for approval',
  act_tell: 'Did it and told us',
  act_quiet: 'Did it quietly',
};
const OUTCOME: Record<AgentProposal['outcome'], string> = { none: 'Not yet judged', accepted: 'Agreed', edited: 'Agreed with changes', rejected: 'Rejected', expired: 'Expired' };

/** The proposals shown on the page as spreadsheet text (what Export CSV saves): when, who, what kind, what it was about, how far it went, what a person made of it and the evidence names. */
export function proposalsCsvText(items: AgentProposal[]): string {
  return csvText(
    ['When', 'Agent', 'Action', 'Target', 'Summary', 'How far it went', 'Confidence', 'Outcome', 'Outcome note', 'Evidence'],
    items.map((p) => [
      p.created_at,
      p.agent,
      p.action_type,
      p.target,
      p.summary,
      RUNG[p.rung] ?? p.rung,
      p.confidence === null ? '' : Math.round(p.confidence * 100) + '%',
      OUTCOME[p.outcome] ?? p.outcome,
      p.outcome_note,
      p.evidence.map((e) => e.label).join('; '),
    ]),
  );
}
