'use client';

/** The security and "what we did" sections of a client's quarterly business review (roadmap r7-af-31), drawn under the client summary so one printed page is the whole pack. No finance information. */
import { useEffect, useState } from 'react';

import { StatCard } from '@/components/ui/kit';
import { authFetch } from '@/lib/auth-session';
import { msspApi } from '@/lib/api';

interface Severities {
  critical: number;
  high: number;
  medium: number;
  low: number;
  info: number;
}
export interface Qbr {
  client: string;
  months: number;
  from: string;
  to: string;
  highlights: string[];
  security: {
    alerts_received: number;
    alerts_received_by_severity: Severities;
    alerts_handled: number;
    alerts_open_now: number;
    alerts_open_now_by_severity: Severities;
    handled_percent: number | null;
    vulnerabilities_open: number;
    vulnerabilities_by_severity: Severities;
    vulnerabilities_exploited: number;
    devices: number;
  };
  work: { cases_opened: number; cases_closed: number; alerts_resolved: number };
}

const key = (s: string): string => s.toLowerCase().replace(/[^a-z0-9]+/g, '');

/** The A.C.O.R.N client whose name is the summary's client (the two systems match on name, ignoring case and punctuation), or null (pure). */
export function clientIdFor(name: string, children: { id: string; name: string }[]): string | null {
  const k = key(name);
  return k ? (children.find((c) => key(c.name) === k)?.id ?? null) : null;
}

const sev = (s: Severities): string =>
  (['critical', 'high', 'medium', 'low'] as const)
    .filter((k) => s[k] > 0)
    .map((k) => `${s[k]} ${k}`)
    .join(', ') || 'none';

export function QbrSecurityBody({ data }: { data: Qbr }) {
  const s = data.security;
  return (
    <section className="space-y-3" data-testid="qbr-security" aria-label="Security and what we did">
      <h2 className="text-sm font-semibold text-white">Security and what we did</h2>
      <ul className="list-disc pl-5 text-sm text-gray-300" data-testid="qbr-highlights">
        {data.highlights.map((h) => (
          <li key={h}>{h}</li>
        ))}
      </ul>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Alerts received" value={String(s.alerts_received)} note={sev(s.alerts_received_by_severity)} />
        <StatCard label="Alerts handled" value={s.handled_percent === null ? '—' : `${s.handled_percent}%`} note={`${s.alerts_handled} of ${s.alerts_received}`} />
        <StatCard label="Open alerts now" value={String(s.alerts_open_now)} note={sev(s.alerts_open_now_by_severity)} />
        <StatCard label="Open vulnerabilities" value={String(s.vulnerabilities_open)} note={s.vulnerabilities_exploited ? `${s.vulnerabilities_exploited} exploited in the wild` : sev(s.vulnerabilities_by_severity)} />
        <StatCard label="Devices" value={String(s.devices)} />
        <StatCard label="Cases closed" value={String(data.work.cases_closed)} note={`${data.work.cases_opened} opened`} />
        <StatCard label="Alerts resolved" value={String(data.work.alerts_resolved)} />
      </div>
      <p className="text-[11px] text-gray-500">
        From {data.from} to {data.to}.
      </p>
    </section>
  );
}

export function QbrSecurity({ clientName, months }: { clientName: string; months: number }) {
  const [data, setData] = useState<Qbr | null>(null);
  useEffect(() => {
    let live = true;
    setData(null);
    void (async () => {
      try {
        const id = clientIdFor(clientName, await msspApi.listChildren());
        if (!id) return;
        const res = await authFetch(`/api/v1/reports/qbr?client_id=${encodeURIComponent(id)}&months=${months}`);
        if (live && res.ok) setData((await res.json()) as Qbr);
      } catch {
        /* the security section is an extra: the rest of the summary stands without it */
      }
    })();
    return () => {
      live = false;
    };
  }, [clientName, months]);
  return data ? <QbrSecurityBody data={data} /> : null;
}
