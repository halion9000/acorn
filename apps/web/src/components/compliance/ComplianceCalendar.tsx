'use client';

/**
 * Compliance calendar: everything that falls due (policy and vendor reviews, scheduled items, open access reviews, the end of unfinished audits) on one list, soonest first, with the overdue ones on top.
 * Each entry links to the page where it is handled. A source the person cannot read, or an older server, just leaves its entries out.
 */
import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';

import { ClientPicker, clientFromAddress } from '@/components/mssp/ClientPicker';
import { authFetch } from '@/lib/auth-session';
import { accessReviewsApi, auditsApi, type AccessReviewRow, type AuditRow } from '@/lib/api';
import { buildCalendar, groupByMonth, type GovernanceDue } from '@/lib/complianceCalendar';
import { withClient } from './GovernancePanel';

const monthName = (ym: string): string => {
  const d = new Date(`${ym}-01T00:00:00Z`);
  return Number.isNaN(d.getTime()) ? ym : d.toLocaleString('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' });
};

export function ComplianceCalendar({ today = new Date().toISOString().slice(0, 10) }: { today?: string } = {}) {
  const [clientId, setClientId] = useState('');
  const [gov, setGov] = useState<GovernanceDue[]>([]);
  const [reviews, setReviews] = useState<AccessReviewRow[]>([]);
  const [audits, setAudits] = useState<AuditRow[]>([]);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    setClientId(clientFromAddress(window.location.search));
  }, []);
  useEffect(() => {
    let live = true;
    setLoaded(false);
    void (async () => {
      const [g, r, a] = await Promise.all([
        authFetch(withClient('/api/v1/governance', clientId)).then((x) => (x.ok ? (x.json() as Promise<GovernanceDue[]>) : [])).catch(() => []),
        accessReviewsApi.list(clientId).then((x) => x.reviews).catch(() => [] as AccessReviewRow[]),
        auditsApi.list(clientId).then((x) => x.audits).catch(() => [] as AuditRow[]),
      ]);
      if (!live) return;
      setGov(Array.isArray(g) ? g : []);
      setReviews(r);
      setAudits(a);
      setLoaded(true);
    })();
    return () => {
      live = false;
    };
  }, [clientId]);
  const groups = useMemo(() => groupByMonth(buildCalendar({ governance: gov, reviews, audits }, today)), [gov, reviews, audits, today]);
  return (
    <div className="space-y-4 p-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Compliance calendar</h1>
        <p className="mt-1 text-sm text-gray-400">Reviews, access reviews and audit periods that fall due, soonest first. Overdue ones are on top.</p>
        <div className="mt-3">
          <ClientPicker value={clientId} onChange={setClientId} label="Whose calendar" />
        </div>
      </div>
      {!loaded && <p className="text-sm text-gray-400">Loading...</p>}
      {loaded && groups.length === 0 && (
        <p className="text-sm text-gray-400" data-testid="calendar-empty">
          Nothing is scheduled. Reviews and audits with a due date appear here.
        </p>
      )}
      {groups.map((g) => (
        <section key={g.label} data-testid="calendar-group">
          <h2 className={`text-sm font-semibold ${g.label === 'Overdue' ? 'text-red-300' : 'text-gray-300'}`}>{g.label === 'Overdue' ? 'Overdue' : monthName(g.label)}</h2>
          <ul className="mt-2 divide-y divide-gray-800 rounded-lg border border-gray-800">
            {g.entries.map((e, i) => (
              <li key={`${e.date}-${e.title}-${i}`} className="flex flex-wrap items-baseline gap-x-3 px-3 py-2 text-sm">
                <span className={`font-mono text-xs ${e.overdue ? 'text-red-300' : 'text-gray-400'}`}>{e.date}</span>
                <span className="rounded-full border border-gray-700 px-2 text-xs text-gray-300">{e.kind}</span>
                <Link href={e.link} className="text-gray-100 hover:underline">
                  {e.title}
                </Link>
                {e.owner && <span className="text-xs text-gray-500">{e.owner}</span>}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
