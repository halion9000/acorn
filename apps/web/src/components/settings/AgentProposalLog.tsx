'use client';

/**
 * The proposal log: every action an agent proposed or took, with the rung of the autonomy ladder it landed on, the evidence it rests on and what a person made of it.
 * "Would have done" rows are shadow mode: nothing happened. A person records the verdict; an agent cannot.
 */

import { useState } from 'react';
import useSWR from 'swr';
import { agentProposalsApi, type AgentProposal } from '@/lib/api';

const RUNG: Record<AgentProposal['rung'], string> = {
  shadow: 'Would have done (nothing happened)',
  suggest: 'Suggested',
  ask: 'Asked for approval',
  act_tell: 'Did it and told us',
  act_quiet: 'Did it quietly',
};

const OUTCOME: Record<AgentProposal['outcome'], string> = {
  none: 'Not yet judged',
  accepted: 'Agreed',
  edited: 'Agreed with changes',
  rejected: 'Rejected',
  expired: 'Expired',
};

export function AgentProposalLog() {
  const [daily, setDaily] = useState(false);
  const { data, error, mutate } = useSWR(['agent-proposals', daily], () => agentProposalsApi.list(daily ? 24 : undefined), { revalidateOnFocus: false, shouldRetryOnError: false });
  const [failed, setFailed] = useState<string | null>(null);

  if (error) return <p className="mb-4 text-sm text-gray-500" data-testid="proposals-error">The proposal log could not be loaded.</p>;
  if (!data) return null;

  async function judge(p: AgentProposal, outcome: 'accepted' | 'rejected') {
    setFailed(null);
    try {
      await agentProposalsApi.setOutcome(p.id, outcome);
      await mutate();
    } catch (e) {
      setFailed(e instanceof Error ? e.message : 'Could not save that.');
    }
  }

  return (
    <section className="mb-6 rounded-lg border border-gray-800 bg-gray-900/60 p-4" data-testid="proposals">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-gray-100">What the agents proposed or did</h3>
        <div className="flex gap-1 text-xs" role="group" aria-label="Period">
          <button type="button" aria-pressed={daily} onClick={() => setDaily(true)} className={`rounded border px-2 py-0.5 ${daily ? 'border-sky-500/60 text-sky-200' : 'border-gray-700 text-gray-400'}`}>Last 24 hours</button>
          <button type="button" aria-pressed={!daily} onClick={() => setDaily(false)} className={`rounded border px-2 py-0.5 ${!daily ? 'border-sky-500/60 text-sky-200' : 'border-gray-700 text-gray-400'}`}>Everything</button>
        </div>
      </div>
      {daily ? (
        <p className="mt-2 text-sm text-gray-300" data-testid="proposals-daily">
          {data.summary.total === 0
            ? 'Nothing from the agents in the last 24 hours.'
            : `In the last 24 hours: ${data.summary.by_rung.act_tell + data.summary.by_rung.act_quiet} done on their own, ${data.summary.by_rung.shadow} recorded as would-have-done, ${data.summary.by_rung.ask} asked for approval, ${data.summary.by_rung.suggest} suggested.`}
        </p>
      ) : null}
      <p className="mt-1 text-xs text-gray-400">
        Each row is one action with the evidence behind it. A row marked &quot;would have done&quot; is shadow mode: nothing happened, and your verdict is what tells us whether the agent could be trusted with it.
        {data.summary.shadow_unreviewed > 0 ? ` ${data.summary.shadow_unreviewed} shadow row${data.summary.shadow_unreviewed === 1 ? '' : 's'} still waiting for a verdict.` : ''}
      </p>
      {failed ? <p className="mt-2 text-sm text-red-300" role="alert">{failed}</p> : null}
      {Object.keys(data.summary.by_agent ?? {}).length > 0 ? (
        <table className="mt-3 w-full text-left text-xs" data-testid="proposals-scorecard">
          <thead className="text-gray-500">
            <tr>
              <th scope="col" className="py-1 pr-3 font-medium">Agent</th>
              <th scope="col" className="py-1 pr-3 font-medium">Logged</th>
              <th scope="col" className="py-1 pr-3 font-medium">Did on its own</th>
              <th scope="col" className="py-1 pr-3 font-medium">Only recorded</th>
              <th scope="col" className="py-1 pr-3 font-medium">Agreed</th>
              <th scope="col" className="py-1 font-medium">Rejected</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(data.summary.by_agent ?? {}).map(([agent, a]) => (
              <tr key={agent} className="border-t border-gray-800" data-testid={`scorecard-${agent}`}>
                <td className="py-1 pr-3 text-gray-200">{agent}</td>
                <td className="py-1 pr-3">{a.total}</td>
                <td className="py-1 pr-3">{a.acted}</td>
                <td className="py-1 pr-3">{a.shadow}</td>
                <td className="py-1 pr-3">{a.accepted + a.edited}</td>
                <td className="py-1">{a.rejected}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {data.items.length === 0 ? (
        <p className="mt-3 text-sm text-gray-500" data-testid="proposals-empty">No agent has logged a proposal yet.</p>
      ) : (
        <ul className="mt-3 space-y-3">
          {data.items.map((p) => (
            <li key={p.id} className="border-t border-gray-800 pt-3 text-sm" data-testid={`proposal-${p.id}`}>
              <p className="text-gray-100">
                <span className="font-medium">{p.agent}</span> · {p.action_type}
                {p.target ? <span className="text-gray-400"> · {p.target}</span> : null}
              </p>
              <p className="mt-0.5 text-gray-300">{p.summary}</p>
              <p className="mt-1 text-xs text-gray-500">
                {RUNG[p.rung]} · {OUTCOME[p.outcome]}
                {p.confidence !== null ? ` · ${Math.round(p.confidence * 100)}% sure` : ''}
              </p>
              <p className="mt-1 text-xs text-gray-400">
                Evidence:{' '}
                {p.evidence.map((e, i) => (
                  <span key={i}>
                    {i > 0 ? ', ' : ''}
                    {e.url ? (
                      <a href={e.url} className="text-sky-300 underline" target="_blank" rel="noreferrer noopener">{e.label}</a>
                    ) : (
                      e.label
                    )}
                  </span>
                ))}
              </p>
              {p.outcome_note ? <p className="mt-1 text-xs text-gray-400">Reason given: {p.outcome_note}</p> : null}
              {p.outcome === 'none' ? (
                <div className="mt-2 flex gap-2">
                  <button type="button" onClick={() => judge(p, 'accepted')} className="rounded border border-emerald-500/40 px-2 py-0.5 text-xs text-emerald-300 hover:bg-emerald-500/10">Agree</button>
                  <button type="button" onClick={() => judge(p, 'rejected')} className="rounded border border-red-500/40 px-2 py-0.5 text-xs text-red-300 hover:bg-red-500/10">Reject</button>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
