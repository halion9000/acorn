'use client';

/**
 * The trust center: what the organization shows its own customers about its security, behind sign-in for now. The left side is the page as a customer would read it (control health of the chosen frameworks as it is
 * now, the chosen policies with when each was last reviewed, the documents); the right side is where a person chooses what goes on it.
 */
import { useCallback, useEffect, useState } from 'react';

import { ClientPicker, clientFromAddress } from '@/components/mssp/ClientPicker';
import { apiErrorDetail, trustCenterApi, type TrustCenter } from '@/lib/api';

const field = 'rounded border border-gray-700 bg-gray-900 px-2 py-1 text-sm text-gray-100';

export function TrustCenterView() {
  const [clientId, setClientId] = useState('');
  const [data, setData] = useState<TrustCenter | null>(null);
  const [problem, setProblem] = useState('');
  const [saved, setSaved] = useState(false);
  const [draft, setDraft] = useState({ enabled: false, headline: '', about: '', contact: '', frameworks: [] as string[], policies: [] as string[], docs: [] as { name: string; url: string }[] });
  const [doc, setDoc] = useState({ name: '', url: '' });

  useEffect(() => {
    setClientId(clientFromAddress(window.location.search));
  }, []);
  const load = useCallback(async () => {
    try {
      const d = await trustCenterApi.get(clientId);
      setData(d);
      setDraft({ enabled: d.enabled, headline: d.headline, about: d.about, contact: d.contact_email ?? '', frameworks: d.chosen_frameworks, policies: d.chosen_policy_ids, docs: d.documents });
      setProblem('');
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'Could not load the trust center.'));
    }
  }, [clientId]);
  useEffect(() => {
    void load();
  }, [load]);

  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  const save = async () => {
    try {
      const out = await trustCenterApi.put(clientId, {
        enabled: draft.enabled, headline: draft.headline, about: draft.about, contact_email: draft.contact.trim() || null, frameworks: draft.frameworks, policy_ids: draft.policies, documents: draft.docs,
      });
      setData(out);
      setSaved(true);
      setProblem('');
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'Could not save.'));
    }
  };

  return (
    <div className="space-y-4 p-6">
      <div className="print:hidden">
        <h1 className="text-2xl font-bold text-white">Trust center</h1>
        <p className="mt-1 text-sm text-gray-400">What you show your customers about your security. It is read by people who sign in; a public link is not built yet. Control health is worked out when the page is read, never typed in.</p>
        <div className="mt-3">
          <ClientPicker value={clientId} onChange={setClientId} label="Whose trust center" />
        </div>
        {data && (
          <button type="button" onClick={() => window.print()} className="mt-3 rounded border border-gray-700 px-3 py-1 text-xs text-gray-200 hover:bg-gray-800">
            Print or save as PDF
          </button>
        )}
      </div>
      {problem && (
        <p role="alert" className="text-sm text-red-300">
          {problem}
        </p>
      )}
      {data === null && !problem && <p className="text-sm text-gray-400">Loading...</p>}
      {data && (
        <div className="grid gap-6 lg:grid-cols-2 print:block">
          <section className="space-y-3 rounded-lg border border-gray-800 bg-gray-900/40 p-4" data-testid="trust-preview">
            <p className="text-xs uppercase text-gray-500">As a customer sees it {data.enabled ? '' : '(not switched on)'}</p>
            <h2 className="text-xl font-semibold text-white">{data.headline || 'Security and compliance'}</h2>
            {data.about && <p className="whitespace-pre-wrap text-sm text-gray-300">{data.about}</p>}
            {data.frameworks.length > 0 && (
              <ul className="space-y-1" data-testid="trust-frameworks">
                {data.frameworks.map((f) => (
                  <li key={f.framework} className="flex justify-between text-sm text-gray-200">
                    <span>{f.framework}</span>
                    <span className="text-gray-400">
                      {f.percent_healthy === null ? 'no controls tested' : `${f.percent_healthy}% of ${f.controls} controls healthy`}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {data.policies.length > 0 && (
              <div data-testid="trust-policies">
                <h3 className="text-sm font-semibold text-gray-200">Policies</h3>
                <ul className="text-sm text-gray-300">
                  {data.policies.map((p) => (
                    <li key={p.id}>
                      {p.title}
                      {p.last_reviewed_at ? <span className="text-xs text-gray-500"> · reviewed {p.last_reviewed_at}</span> : null}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {data.documents.length > 0 && (
              <div data-testid="trust-documents">
                <h3 className="text-sm font-semibold text-gray-200">Documents</h3>
                <ul className="text-sm">
                  {data.documents.map((d) => (
                    <li key={d.url}>
                      <a href={d.url} target="_blank" rel="noopener noreferrer" className="text-blue-300 hover:underline">
                        {d.name}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {data.contact_email && <p className="text-sm text-gray-300">Questions: {data.contact_email}</p>}
          </section>
          <section className="space-y-3 rounded-lg border border-gray-700 bg-gray-900/60 p-4 print:hidden" data-testid="trust-editor">
            <label className="flex items-center gap-2 text-sm text-gray-200">
              <input type="checkbox" checked={draft.enabled} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} />
              Switch the trust center on
            </label>
            <label className="block text-xs text-gray-400">
              Headline
              <input aria-label="Headline" value={draft.headline} onChange={(e) => setDraft({ ...draft, headline: e.target.value })} className={`${field} mt-1 block w-full`} />
            </label>
            <label className="block text-xs text-gray-400">
              About
              <textarea aria-label="About" rows={4} value={draft.about} onChange={(e) => setDraft({ ...draft, about: e.target.value })} className={`${field} mt-1 block w-full`} />
            </label>
            <label className="block text-xs text-gray-400">
              Contact address
              <input aria-label="Contact address" type="email" value={draft.contact} onChange={(e) => setDraft({ ...draft, contact: e.target.value })} className={`${field} mt-1 block w-full`} />
            </label>
            <fieldset>
              <legend className="text-xs text-gray-400">Frameworks to show (the ones turned on)</legend>
              {data.available_frameworks.length === 0 && <p className="text-xs text-gray-500">No framework is turned on. Turn one on in the Compliance overview.</p>}
              {data.available_frameworks.map((f) => (
                <label key={f} className="mr-4 inline-flex items-center gap-1 text-sm text-gray-200">
                  <input type="checkbox" aria-label={`Show ${f}`} checked={draft.frameworks.includes(f)} onChange={() => setDraft({ ...draft, frameworks: toggle(draft.frameworks, f) })} />
                  {f}
                </label>
              ))}
            </fieldset>
            <fieldset>
              <legend className="text-xs text-gray-400">Policies to list</legend>
              {data.available_policies.length === 0 && <p className="text-xs text-gray-500">No policies yet. Add some on the Policies page.</p>}
              {data.available_policies.map((p) => (
                <label key={p.id} className="block text-sm text-gray-200">
                  <input type="checkbox" aria-label={`List ${p.title}`} checked={draft.policies.includes(p.id)} onChange={() => setDraft({ ...draft, policies: toggle(draft.policies, p.id) })} /> {p.title}
                </label>
              ))}
            </fieldset>
            <fieldset>
              <legend className="text-xs text-gray-400">Documents (a name and a link)</legend>
              <ul className="text-sm text-gray-300">
                {draft.docs.map((d) => (
                  <li key={d.url}>
                    {d.name}{' '}
                    <button type="button" aria-label={`Remove ${d.name}`} onClick={() => setDraft({ ...draft, docs: draft.docs.filter((x) => x.url !== d.url) })} className="text-xs text-gray-500 hover:text-red-300">
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
              <div className="mt-1 flex gap-2">
                <input aria-label="Document name" placeholder="Name" value={doc.name} onChange={(e) => setDoc({ ...doc, name: e.target.value })} className={`${field} w-40`} />
                <input aria-label="Document link" placeholder="https://" value={doc.url} onChange={(e) => setDoc({ ...doc, url: e.target.value })} className={`${field} flex-1`} />
                <button type="button" disabled={doc.name.trim().length < 2 || doc.url.trim().length < 8} onClick={() => { setDraft({ ...draft, docs: [...draft.docs, { name: doc.name.trim(), url: doc.url.trim() }] }); setDoc({ name: '', url: '' }); }} className="rounded border border-gray-700 px-3 py-1 text-xs text-gray-200 hover:bg-gray-800 disabled:opacity-40">
                  Add document
                </button>
              </div>
            </fieldset>
            <div className="flex items-center gap-3">
              <button type="button" onClick={() => void save()} className="rounded bg-blue-600 px-3 py-1 text-sm text-white hover:bg-blue-500">
                Save
              </button>
              {saved && <span className="text-xs text-emerald-300">Saved.</span>}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
