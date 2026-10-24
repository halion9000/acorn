"use client";

/**
 * What ThreatMate says about the client: its security score, how many devices are patch-compliant, and end-of-life software. Plain checks CORE reads from ThreatMate once a day and sends for a
 * client that is mapped to it. Nothing is shown for a client with none (not mapped, or nothing sent yet).
 */

export interface PostureCheck {
  key: string;
  status: 'met' | 'partly' | 'not_met' | string;
  evidence: string;
}

const TITLE: Record<string, string> = {
  threatmate_security_score: 'Security score',
  threatmate_patching: 'Patching',
  threatmate_end_of_life: 'End-of-life software',
};

const STATUS: Record<string, { text: string; className: string }> = {
  met: { text: 'Good', className: 'border-emerald-500/40 text-emerald-300' },
  partly: { text: 'Needs attention', className: 'border-amber-500/40 text-amber-300' },
  not_met: { text: 'Problem', className: 'border-red-500/40 text-red-300' },
};

export function ThreatMateChecks({ checks, refreshedAt }: { checks: PostureCheck[]; refreshedAt?: string | null }) {
  if (checks.length === 0) return null;
  return (
    <section data-testid="threatmate-checks">
      <h3 className="mb-2 text-sm uppercase text-slate-500">
        ThreatMate{refreshedAt ? <span className="ml-2 text-xs normal-case text-slate-600">as of {new Date(refreshedAt).toLocaleDateString()}</span> : null}
      </h3>
      <div className="grid gap-2 md:grid-cols-3">
        {checks.map((c) => {
          const st = STATUS[c.status] ?? STATUS.partly;
          return (
            <div key={c.key} className="rounded border border-slate-800 p-2" data-testid={`tm-${c.key}`}>
              <div className="text-xs uppercase text-slate-500">{TITLE[c.key] ?? c.key.replace(/^threatmate_/, '').replace(/_/g, ' ')}</div>
              <span className={`mt-1 inline-block rounded border px-1.5 py-0.5 text-[11px] ${st.className}`}>{st.text}</span>
              <div className="mt-1 text-xs text-slate-400">{c.evidence}</div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
