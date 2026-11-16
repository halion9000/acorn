'use client';

/**
 * Under a domain's report: what to publish in its DMARC record next (as the exact line to put in DNS, with the reporting address A.C.O.R.N already gave this domain) and which failing senders to fix
 * first. The thresholds are in lib/dmarcAdvice.ts. Read only: nothing here changes DNS.
 */
import { useState } from 'react';
import useSWR from 'swr';

import { authFetch } from '@/lib/auth-session';
import { buildDmarcRecord, fixList, nextStep, type FailingSource } from '@/lib/dmarcAdvice';

interface SetupLines {
  lines?: { domain: string; client_dmarc_rua?: string }[];
}

const fetcher = async (url: string): Promise<SetupLines> => {
  const res = await authFetch(url);
  if (!res.ok) throw new Error(String(res.status));
  return res.json();
};

export function DmarcNextStep({ domain, rollup, sources }: { domain: string; rollup: { policy: string; total: number; passed: number; failed: number }; sources: FailingSource[] }) {
  // The reporting address is optional: without it the record is still correct, just without the rua tag.
  const { data } = useSWR<SetupLines>('/api/v1/dmarc/setup', fetcher, { shouldRetryOnError: false });
  const [copied, setCopied] = useState(false);
  const step = nextStep(rollup);
  const rua = data?.lines?.find((l) => l.domain.toLowerCase() === domain.toLowerCase())?.client_dmarc_rua ?? null;
  const record = buildDmarcRecord({ policy: step.policy, pct: step.pct, rua });
  const fixes = fixList(sources);
  return (
    <section aria-label="What to do next" className="mt-5 rounded-lg border border-gray-800 bg-gray-950/40 p-4">
      <h4 className="text-sm font-medium text-gray-200">What to do next</h4>
      <p className={`mt-1 text-sm ${step.change ? 'text-sky-300' : 'text-gray-300'}`}>{step.headline}</p>
      <ul className="mt-1 list-disc space-y-1 pl-5 text-xs text-gray-400">
        {step.reasons.map((t) => (
          <li key={t}>{t}</li>
        ))}
      </ul>
      {step.change && (
        <div className="mt-3">
          <p className="text-xs text-gray-500">
            Publish this as a TXT record named <span className="font-mono text-gray-300">_dmarc.{domain}</span>:
          </p>
          <div className="mt-1 flex items-start gap-2">
            <code className="flex-1 break-all rounded bg-gray-900 px-2 py-1 font-mono text-xs text-gray-200" data-testid="dmarc-record">
              {record}
            </code>
            <button
              type="button"
              aria-label="Copy the DMARC record"
              onClick={() => {
                void navigator.clipboard?.writeText(record).then(() => {
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1500);
                });
              }}
              className="rounded border border-gray-700 px-2 py-0.5 text-xs text-gray-300 hover:bg-gray-800"
            >
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
        </div>
      )}
      {fixes.length > 0 && (
        <>
          <p className="mt-3 text-xs font-medium text-gray-300">Fix these first</p>
          <ol className="mt-1 list-decimal space-y-1 pl-5 text-xs text-gray-400" data-testid="dmarc-fixes">
            {fixes.map((f) => (
              <li key={f.text}>
                {f.text} <span className="text-gray-500">({f.share}% of failures)</span>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}
