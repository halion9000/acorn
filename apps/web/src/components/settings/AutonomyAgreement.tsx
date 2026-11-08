'use client';

/**
 * How often people agree with what an agent proposed, per kind of action (the autonomy plan's agreement rate).
 * Reports and suggests only: a person still sets every autonomy level in the editor below.
 */

import useSWR from 'swr';
import { approvalAgreementApi, type ApprovalAgreementRow } from '@/lib/api';

const TONE: Record<ApprovalAgreementRow['suggestion'], string> = {
  promote: 'text-emerald-300',
  keep: 'text-gray-300',
  demote: 'text-amber-300',
  'too few': 'text-gray-500',
};

const WORDS: Record<ApprovalAgreementRow['suggestion'], string> = {
  promote: 'Could act more on its own',
  keep: 'Keep as it is',
  demote: 'Ask a person more often',
  'too few': 'Too few decisions to say',
};

export function AutonomyAgreement() {
  const { data, error } = useSWR('approval-agreement', () => approvalAgreementApi.get(), { revalidateOnFocus: false, shouldRetryOnError: false });
  if (error) return <p className="mb-4 text-sm text-gray-500" data-testid="agreement-error">The agreement rates could not be loaded.</p>;
  if (!data) return null;
  return (
    <section className="mb-6 rounded-lg border border-gray-800 bg-gray-900/60 p-4" data-testid="agreement">
      <h3 className="text-sm font-semibold text-gray-100">How often people agree with the agents (last {data.window_days} days)</h3>
      <p className="mt-1 text-xs text-gray-400">{data.rules}</p>
      {data.rows.length === 0 ? (
        <p className="mt-3 text-sm text-gray-500" data-testid="agreement-empty">No agent has asked for approval in this period yet.</p>
      ) : (
        <table className="mt-3 w-full text-left text-sm">
          <thead className="text-xs text-gray-500">
            <tr>
              <th scope="col" className="py-1 pr-3">Kind of action</th>
              <th scope="col" className="py-1 pr-3">Asked</th>
              <th scope="col" className="py-1 pr-3">Approved</th>
              <th scope="col" className="py-1 pr-3">Denied</th>
              <th scope="col" className="py-1 pr-3">Expired</th>
              <th scope="col" className="py-1 pr-3">Agreement</th>
              <th scope="col" className="py-1">Suggestion</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.action} className="border-t border-gray-800" data-testid={`agreement-${r.action}`}>
                <td className="py-1.5 pr-3 text-gray-200">{r.action}</td>
                <td className="py-1.5 pr-3">{r.proposed}</td>
                <td className="py-1.5 pr-3">{r.approved}</td>
                <td className="py-1.5 pr-3">{r.denied}</td>
                <td className="py-1.5 pr-3">{r.expired}</td>
                <td className="py-1.5 pr-3">{r.agreement === null ? '—' : `${Math.round(r.agreement * 100)}%`}</td>
                <td className={`py-1.5 ${TONE[r.suggestion]}`}>{WORDS[r.suggestion]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
