'use client';

/**
 * Secureframe's policies and risk register on the Compliance index, as CORE last read them (the same answer the Secureframe card reads). A policy shows its name, whether it is published
 * and how many of the people who must accept it have, the least accepted first; never its text. A risk shows what it is, what was decided about it, and its rating before and after
 * treatment, the highest remaining risk first. Nothing is shown until CORE has sent the lists (an older report carries only the counts).
 */
import useSWR from 'swr';

import { authFetch } from '@/lib/auth-session';

export interface PolicyLine {
  name: string;
  status?: string | null;
  published_at?: string | null;
  accepted: number;
  eligible: number;
  frameworks?: string[];
}

export interface RiskLine {
  id?: string | null;
  description: string;
  status?: string | null;
  treatment?: string | null;
  categories?: string[];
  impact?: number | null;
  likelihood?: number | null;
  residual_impact?: number | null;
  residual_likelihood?: number | null;
}

interface Answer {
  report: { policy_list?: PolicyLine[]; risk_list?: RiskLine[] } | null;
}

async function read(): Promise<Answer> {
  const res = await authFetch('/api/v1/secureframe');
  if (!res.ok) throw new Error(`The API answered ${res.status}`);
  return (await res.json()) as Answer;
}

/** The share of the people who must accept a policy that have, as a whole percentage; null when nobody has to. */
export function acceptancePercent(p: Pick<PolicyLine, 'accepted' | 'eligible'>): number | null {
  return p.eligible > 0 ? Math.round((Math.min(p.accepted, p.eligible) / p.eligible) * 100) : null;
}

/** Impact times likelihood, or null when either is missing. */
export function riskScore(impact: number | null | undefined, likelihood: number | null | undefined): number | null {
  return typeof impact === 'number' && typeof likelihood === 'number' ? impact * likelihood : null;
}

/** "12 (impact 4 × likelihood 3)", or a dash when it was not rated. */
export function riskRating(impact: number | null | undefined, likelihood: number | null | undefined): string {
  const score = riskScore(impact, likelihood);
  return score === null ? '—' : `${score} (impact ${impact} × likelihood ${likelihood})`;
}

const word = (v: string | null | undefined): string => (v ? v.replace(/_/g, ' ') : '—');

export function SecureframeRegisters() {
  const { data, error } = useSWR('secureframe-registers', read, { revalidateOnFocus: false, shouldRetryOnError: false });
  if (error || !data?.report) return null;
  const policies = data.report.policy_list ?? [];
  const risks = data.report.risk_list ?? [];
  if (policies.length === 0 && risks.length === 0) return null;
  const waiting = policies.filter((p) => (acceptancePercent(p) ?? 100) < 100).length;
  const unpublished = policies.filter((p) => p.status !== 'published').length;
  return (
    <div className="space-y-4" data-testid="secureframe-registers">
      {policies.length > 0 && (
        <section className="rounded-lg border border-gray-700 bg-gray-800 p-5" aria-label="Secureframe policies">
          <h2 className="text-base font-semibold text-white">Policies in Secureframe</h2>
          <p className="mt-1 text-sm text-gray-300" data-testid="policies-summary">
            {policies.length} {policies.length === 1 ? 'policy' : 'policies'}: {waiting} not yet accepted by everyone who must{unpublished ? `, ${unpublished} not published` : ''}. The least accepted first.
          </p>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-gray-500">
                <tr>
                  <th scope="col" className="py-1 pr-3">Policy</th>
                  <th scope="col" className="py-1 pr-3">Status</th>
                  <th scope="col" className="py-1 pr-3">Accepted</th>
                  <th scope="col" className="w-1/4 py-1 pr-3" aria-hidden="true" />
                  <th scope="col" className="py-1">Published</th>
                </tr>
              </thead>
              <tbody>
                {policies.map((p) => {
                  const pct = acceptancePercent(p);
                  return (
                    <tr key={p.name} className="border-t border-gray-700" data-testid="policy-row">
                      <td className="py-1.5 pr-3 text-gray-100">
                        {p.name}
                        {(p.frameworks ?? []).length > 0 ? <span className="block text-xs text-gray-500">{p.frameworks!.join(', ')}</span> : null}
                      </td>
                      <td className={`py-1.5 pr-3 ${p.status === 'published' ? 'text-gray-300' : 'text-amber-300'}`}>{word(p.status)}</td>
                      <td className={`py-1.5 pr-3 tabular-nums ${pct === null ? 'text-gray-500' : pct === 100 ? 'text-emerald-300' : pct >= 80 ? 'text-amber-300' : 'text-red-300'}`}>
                        {pct === null ? 'nobody has to' : `${p.accepted} of ${p.eligible} (${pct}%)`}
                      </td>
                      <td className="py-1.5 pr-3">
                        <div className="h-2 overflow-hidden rounded bg-gray-900">
                          <div className={`h-full ${pct === 100 ? 'bg-emerald-500' : (pct ?? 0) >= 80 ? 'bg-amber-400' : 'bg-red-500'}`} style={{ width: `${pct ?? 0}%` }} />
                        </div>
                      </td>
                      <td className="py-1.5 text-xs text-gray-400">{p.published_at ? p.published_at.slice(0, 10) : '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
      {risks.length > 0 && (
        <section className="rounded-lg border border-gray-700 bg-gray-800 p-5" aria-label="Secureframe risk register">
          <h2 className="text-base font-semibold text-white">Risk register in Secureframe</h2>
          <p className="mt-1 text-sm text-gray-300" data-testid="risks-summary">
            {risks.length} {risks.length === 1 ? 'risk' : 'risks'}: {risks.filter((r) => r.treatment === 'mitigate').length} being mitigated, {risks.filter((r) => r.treatment === 'accept').length} accepted. The highest remaining risk first.
          </p>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-gray-500">
                <tr>
                  <th scope="col" className="py-1 pr-3">Risk</th>
                  <th scope="col" className="py-1 pr-3">Decision</th>
                  <th scope="col" className="py-1 pr-3">Status</th>
                  <th scope="col" className="py-1 pr-3">Before treatment</th>
                  <th scope="col" className="py-1">After treatment</th>
                </tr>
              </thead>
              <tbody>
                {risks.map((r, i) => (
                  <tr key={`${r.id ?? ''}-${i}`} className="border-t border-gray-700 align-top" data-testid="risk-row">
                    <td className="py-1.5 pr-3 text-gray-100">
                      {r.id ? <span className="mr-2 font-mono text-xs text-gray-500">{r.id}</span> : null}
                      {r.description}
                      {(r.categories ?? []).length > 0 ? <span className="block text-xs text-gray-500">{r.categories!.join(', ')}</span> : null}
                    </td>
                    <td className="py-1.5 pr-3 text-gray-300">{word(r.treatment)}</td>
                    <td className="py-1.5 pr-3 text-gray-300">{word(r.status)}</td>
                    <td className="py-1.5 pr-3 tabular-nums text-gray-300">{riskRating(r.impact, r.likelihood)}</td>
                    <td className="py-1.5 tabular-nums text-gray-100">{riskRating(r.residual_impact, r.residual_likelihood)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
