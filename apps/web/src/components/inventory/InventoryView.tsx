'use client';

/**
 * The stock Live Oak holds for clients (parts, drives, workstations held for a client) and the NUCs, with who has each one and what has happened to it. Replaces the SharePoint inventory lists. Every item belongs to a client's
 * own tenant (or Live Oak's), so this is also the page a client portal will show a client, for that client only. Reading needs alerts:read; changing things needs mssp:manage (the API says no, and the page shows its message).
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import useSWR from 'swr';

import { inventoryApi, msspApi, type InventoryImportResult, type InventorySyncResult, type InventoryNucSyncResult, type InventoryItem, type InventoryKind, type InventoryQuery, type InventoryStatus } from '@/lib/api';
import { safeDistance } from '@/lib/safe-date';

export const STATUS_LABEL: Record<InventoryStatus, string> = { checked_in: 'Checked in', checked_out: 'Checked out', offline: 'Offline', retired: 'Retired' };
const STATUS_STYLE: Record<InventoryStatus, string> = {
  checked_in: 'bg-sky-500/15 text-sky-300',
  checked_out: 'bg-emerald-500/15 text-emerald-300',
  offline: 'bg-amber-500/15 text-amber-300',
  retired: 'bg-gray-700 text-gray-300',
};

/** "Acme Dental", "Live Oak (own)" or the customer as written when it has not been matched to a client yet. */
export function holderLabel(i: Pick<InventoryItem, 'client_name' | 'customer_name'>): string {
  if (i.client_name) return i.client_name;
  return i.customer_name ? `${i.customer_name} (not matched)` : 'Live Oak (own)';
}

const dateText = (d: string | null) => (d ? new Date(`${d}T00:00:00`).toLocaleDateString() : '—');
const input = 'rounded-md border border-gray-700 bg-gray-900 px-2 py-1.5 text-sm text-white';

function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className={`mt-10 w-full ${wide ? 'max-w-3xl' : 'max-w-lg'} rounded-xl border border-gray-700 bg-gray-900 p-5 shadow-xl`}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="text-gray-400 hover:text-white">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-xs text-gray-400">
      {label}
      <div className="mt-0.5">{children}</div>
    </label>
  );
}

type Clients = { id: string; name: string }[];

function ItemForm({ kind, item, clients, onDone, onClose }: { kind: InventoryKind; item?: InventoryItem; clients: Clients; onDone: () => void; onClose: () => void }) {
  const [f, setF] = useState({
    name: item?.name ?? '',
    client: item ? (item.client_id ?? 'own') : 'own',
    serial: item?.serial ?? '',
    category: item?.category ?? '',
    model: item?.model ?? '',
    quantity: String(item?.quantity ?? 1),
    status: (item?.status ?? 'checked_in') as InventoryStatus,
    site: item?.site ?? '',
    person: item?.person ?? '',
    notes: item?.notes ?? '',
    tags: (item?.tags ?? []).join(', '),
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setF((p) => ({ ...p, [k]: e.target.value }));
  const save = async () => {
    setBusy(true);
    setError(null);
    const body = {
      name: f.name.trim(),
      serial: f.serial.trim() || null,
      category: f.category.trim() || null,
      model: f.model.trim() || null,
      quantity: Number(f.quantity) || 0,
      status: f.status,
      site: f.site.trim() || null,
      person: f.person.trim() || null,
      notes: f.notes.trim() || null,
      tags: f.tags.split(',').map((t) => t.trim()).filter(Boolean),
    };
    try {
      if (item) await inventoryApi.update(item.id, { ...body, ...(f.client === 'own' ? { move_to_own: true } : { client_id: f.client }) });
      else await inventoryApi.create({ ...body, kind, ...(f.client === 'own' ? {} : { client_id: f.client }) });
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save the item.');
      setBusy(false);
    }
  };
  return (
    <Modal title={item ? `Edit ${item.name}` : kind === 'nuc' ? 'Add a NUC' : 'Add an item'} onClose={onClose}>
      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2">
          <Field label={kind === 'nuc' ? 'Computer name' : 'Name'}>
            <input aria-label="Name" value={f.name} onChange={set('name')} className={`${input} w-full`} />
          </Field>
        </div>
        <div className="col-span-2">
          <Field label="Client">
            <select aria-label="Client" value={f.client} onChange={set('client')} className={`${input} w-full`}>
              <option value="own">Live Oak (own stock)</option>
              {clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Serial number (optional)">
          <input aria-label="Serial number" value={f.serial} onChange={set('serial')} className={`${input} w-full`} />
        </Field>
        <Field label="Model">
          <input aria-label="Model" value={f.model} onChange={set('model')} className={`${input} w-full`} />
        </Field>
        {kind === 'stock' && (
          <>
            <Field label="Category">
              <input aria-label="Category" value={f.category} onChange={set('category')} className={`${input} w-full`} />
            </Field>
            <Field label="Quantity">
              <input aria-label="Quantity" type="number" min={0} value={f.quantity} onChange={set('quantity')} className={`${input} w-full`} />
            </Field>
          </>
        )}
        <Field label="Status">
          <select aria-label="Status" value={f.status} onChange={set('status')} className={`${input} w-full`}>
            {(Object.keys(STATUS_LABEL) as InventoryStatus[]).map((s) => (
              <option key={s} value={s}>
                {STATUS_LABEL[s]}
              </option>
            ))}
          </select>
        </Field>
        <Field label={kind === 'nuc' ? 'Site location' : 'Site'}>
          <input aria-label="Site" value={f.site} onChange={set('site')} className={`${input} w-full`} />
        </Field>
        <Field label="With (person)">
          <input aria-label="Person" value={f.person} onChange={set('person')} className={`${input} w-full`} />
        </Field>
        <Field label="Tags (comma separated)">
          <input aria-label="Tags" value={f.tags} onChange={set('tags')} className={`${input} w-full`} />
        </Field>
        <div className="col-span-2">
          <Field label="Notes">
            <textarea aria-label="Notes" value={f.notes} onChange={set('notes')} rows={3} className={`${input} w-full`} />
          </Field>
        </div>
      </div>
      {error && (
        <p role="alert" className="mt-3 text-sm text-red-300">
          {error}
        </p>
      )}
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="rounded-md border border-gray-700 px-3 py-1.5 text-sm text-gray-300">
          Cancel
        </button>
        <button type="button" disabled={busy || !f.name.trim()} onClick={() => void save()} className="rounded-md bg-sky-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">
          {item ? 'Save' : 'Add'}
        </button>
      </div>
    </Modal>
  );
}

function MoveForm({ item, mode, onDone, onClose }: { item: InventoryItem; mode: 'out' | 'in'; onDone: () => void; onClose: () => void }) {
  const [person, setPerson] = useState(item.person && item.person.toLowerCase() !== 'spare' ? item.person : '');
  const [site, setSite] = useState(item.site ?? '');
  const [ticket, setTicket] = useState('');
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    setError(null);
    try {
      if (mode === 'out') await inventoryApi.checkOut(item.id, { person: person.trim() || undefined, site: site.trim() || undefined, ticket_url: ticket.trim() || undefined, note: note.trim() || undefined });
      else await inventoryApi.checkIn(item.id, { note: note.trim() || undefined, ticket_url: ticket.trim() || undefined });
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not record that.');
      setBusy(false);
    }
  };
  return (
    <Modal title={`${mode === 'out' ? 'Check out' : 'Check in'} ${item.name}`} onClose={onClose}>
      <div className="space-y-3">
        {mode === 'out' && (
          <>
            <Field label="Who has it">
              <input aria-label="Who has it" value={person} onChange={(e) => setPerson(e.target.value)} className={`${input} w-full`} />
            </Field>
            <Field label="Site">
              <input aria-label="Site" value={site} onChange={(e) => setSite(e.target.value)} className={`${input} w-full`} />
            </Field>
          </>
        )}
        <Field label="HaloPSA ticket link (optional)">
          <input aria-label="Ticket link" value={ticket} onChange={(e) => setTicket(e.target.value)} placeholder="https://..." className={`${input} w-full`} />
        </Field>
        <Field label="Note (optional)">
          <textarea aria-label="Note" value={note} onChange={(e) => setNote(e.target.value)} rows={2} className={`${input} w-full`} />
        </Field>
      </div>
      {error && (
        <p role="alert" className="mt-3 text-sm text-red-300">
          {error}
        </p>
      )}
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="rounded-md border border-gray-700 px-3 py-1.5 text-sm text-gray-300">
          Cancel
        </button>
        <button type="button" disabled={busy} onClick={() => void go()} className="rounded-md bg-sky-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">
          {mode === 'out' ? 'Check out' : 'Check in'}
        </button>
      </div>
    </Modal>
  );
}

function History({ item, onClose }: { item: InventoryItem; onClose: () => void }) {
  const { data, error } = useSWR(['inventory-events', item.id], () => inventoryApi.events(item.id), { revalidateOnFocus: false });
  return (
    <Modal title={`History of ${item.name}`} onClose={onClose}>
      {error && <p className="text-sm text-red-300">Could not load the history.</p>}
      {!data && !error && <p className="text-sm text-gray-400">Loading...</p>}
      {data && data.length === 0 && <p className="text-sm text-gray-400">Nothing recorded yet.</p>}
      <ul className="space-y-2 text-sm" data-testid="history">
        {(data ?? []).map((e) => (
          <li key={e.id} className="rounded border border-gray-800 p-2">
            <span className="font-medium text-gray-100">{e.event.replace('_', ' ')}</span>
            <span className="ml-2 text-xs text-gray-500">{new Date(e.at).toLocaleString()}</span>
            {e.actor && <span className="ml-2 text-xs text-gray-500">by {e.actor}</span>}
            {e.person && <div className="text-gray-300">With: {e.person}</div>}
            {e.note && <div className="text-gray-300">{e.note}</div>}
            {e.ticket_url && (
              <a href={e.ticket_url} target="_blank" rel="noopener noreferrer" className="text-xs text-sky-300 hover:underline">
                Ticket
              </a>
            )}
          </li>
        ))}
      </ul>
    </Modal>
  );
}

const PLACEMENT_TEXT: Record<InventoryImportResult['customers'][number]['placed'], string> = {
  exact: 'matched to a client',
  own: "Live Oak's own",
  chosen: 'as you chose',
  unmatched: 'no client matched',
  skipped: 'left out',
};

function ImportForm({ kind, clients, onDone, onClose }: { kind: InventoryKind; clients: Clients; onDone: () => void; onClose: () => void }) {
  const [text, setText] = useState('');
  const [fileName, setFileName] = useState('');
  const [defaultClient, setDefaultClient] = useState('');
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<InventoryImportResult | null>(null);
  const [result, setResult] = useState<InventoryImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const body = (dry: boolean) => ({ kind, csv_text: text, dry_run: dry, ...(defaultClient ? { default_client_id: defaultClient } : {}), mapping });
  const run = async (dry: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const r = await inventoryApi.import(body(dry));
      if (dry) setPreview(r);
      else {
        setResult(r);
        onDone();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not read that list.');
    } finally {
      setBusy(false);
    }
  };
  const readFile = async (file: File | undefined) => {
    if (!file) return;
    setFileName(file.name);
    setText(await file.text());
    setPreview(null);
  };
  return (
    <Modal title={`Import a ${kind === 'nuc' ? 'NUC' : 'stock'} list from SharePoint`} onClose={onClose} wide>
      {result ? (
        <div data-testid="import-result" className="space-y-2 text-sm text-gray-200">
          <p>
            Done: {result.created} added, {result.updated} updated, {result.skipped} left out.
          </p>
          <button type="button" onClick={onClose} className="rounded-md bg-sky-600 px-3 py-1.5 text-sm text-white">
            Close
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-xs text-gray-400">
            Export the SharePoint list to CSV (Export, then Export to CSV) and choose the file. Importing the same list again updates what is there; it never duplicates.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <input ref={fileRef} type="file" accept=".csv,text/csv" aria-label="CSV file" className="hidden" onChange={(e) => void readFile(e.target.files?.[0])} />
            <button type="button" onClick={() => fileRef.current?.click()} className="rounded-md border border-gray-700 bg-gray-900 px-3 py-1.5 text-sm text-white">
              Choose a CSV file
            </button>
            <span className="text-xs text-gray-400">{fileName || 'No file chosen'}</span>
          </div>
          <Field label="This file is for one client (a per-client list with no Customer column)">
            <select aria-label="Client for the whole file" value={defaultClient} onChange={(e) => { setDefaultClient(e.target.value); setPreview(null); }} className={`${input} w-full`}>
              <option value="">No: use the Customer column</option>
              {clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
          {error && (
            <p role="alert" className="text-sm text-red-300">
              {error}
            </p>
          )}
          {preview && (
            <div data-testid="import-preview" className="space-y-2">
              <p className="text-sm text-gray-200">
                {preview.rows} rows read: {preview.created} would be added or updated, {preview.skipped} left out.
              </p>
              {preview.problems.length > 0 && <p className="text-xs text-amber-300">{preview.problems.slice(0, 3).join('; ')}</p>}
              <div className="max-h-72 overflow-y-auto rounded border border-gray-800">
                <table className="w-full text-left text-xs">
                  <thead className="sticky top-0 bg-gray-900 text-gray-400">
                    <tr>
                      <th className="px-2 py-1">Customer</th>
                      <th className="px-2 py-1">Rows</th>
                      <th className="px-2 py-1">Goes to</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.customers.map((c) => (
                      <tr key={c.name} className="border-t border-gray-800" data-testid="import-customer">
                        <td className="px-2 py-1 text-gray-200">{c.name || '(none)'}</td>
                        <td className="px-2 py-1 text-gray-400">{c.rows}</td>
                        <td className="px-2 py-1">
                          {c.placed === 'unmatched' && c.name ? (
                            <select
                              aria-label={`Place ${c.name}`}
                              value={mapping[c.name.toLowerCase()] ?? ''}
                              onChange={(e) => {
                                const v = e.target.value;
                                setMapping((m) => {
                                  const next = { ...m };
                                  if (v) next[c.name.toLowerCase()] = v;
                                  else delete next[c.name.toLowerCase()];
                                  return next;
                                });
                              }}
                              className="rounded border border-gray-700 bg-gray-900 px-1 py-0.5 text-xs text-white"
                            >
                              <option value="">Keep as Live Oak&apos;s, with this name</option>
                              {c.suggestions.map((s) => (
                                <option key={s.client_id} value={s.client_id}>
                                  Suggested: {s.client_name}
                                </option>
                              ))}
                              <option value="own">Live Oak&apos;s own</option>
                              <option value="skip">Leave these out</option>
                              {clients.map((k) => (
                                <option key={k.id} value={k.id}>
                                  {k.name}
                                </option>
                              ))}
                            </select>
                          ) : (
                            <span className="text-gray-300">
                              {c.client_name ?? PLACEMENT_TEXT[c.placed]}
                              {c.client_name ? ` (${PLACEMENT_TEXT[c.placed]})` : ''}
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          <div className="flex justify-end gap-2">
            <button type="button" disabled={busy || !text} onClick={() => void run(true)} className="rounded-md border border-gray-700 px-3 py-1.5 text-sm text-white disabled:opacity-50">
              {preview ? 'Preview again' : 'Preview'}
            </button>
            <button type="button" disabled={busy || !preview} onClick={() => void run(false)} className="rounded-md bg-sky-600 px-3 py-1.5 text-sm text-white disabled:opacity-50">
              Import
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}

function BulkForm({ ids, clients, onDone, onClose }: { ids: string[]; clients: Clients; onDone: () => void; onClose: () => void }) {
  const [client, setClient] = useState('');
  const [category, setCategory] = useState('');
  const [site, setSite] = useState('');
  const [tag, setTag] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const nothing = !client && !category.trim() && !site.trim() && !tag.trim();
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await inventoryApi.bulk({
        ids,
        ...(client === 'own' ? { move_to_own: true } : client ? { client_id: client } : {}),
        ...(category.trim() ? { category: category.trim() } : {}),
        ...(site.trim() ? { site: site.trim() } : {}),
        ...(tag.trim() ? { add_tags: [tag.trim()] } : {}),
      });
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save the changes.');
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title={`Edit ${ids.length} items`} onClose={onClose}>
      <p className="mb-3 text-xs text-gray-400">Only the fields you fill in change. Everything else on each item stays as it is.</p>
      <div className="space-y-3">
        <Field label="Move to client">
          <select aria-label="Move to client" value={client} onChange={(e) => setClient(e.target.value)} className={`${input} w-full`}>
            <option value="">Leave as it is</option>
            <option value="own">Live Oak (own stock)</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Set category">
          <input aria-label="Set category" value={category} onChange={(e) => setCategory(e.target.value)} className={`${input} w-full`} />
        </Field>
        <Field label="Set site">
          <input aria-label="Set site" value={site} onChange={(e) => setSite(e.target.value)} className={`${input} w-full`} />
        </Field>
        <Field label="Add a tag">
          <input aria-label="Add a tag" value={tag} onChange={(e) => setTag(e.target.value)} className={`${input} w-full`} />
        </Field>
      </div>
      {error && (
        <p role="alert" className="mt-3 text-sm text-red-300">
          {error}
        </p>
      )}
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onClose} className={`${input} hover:bg-gray-800`}>
          Cancel
        </button>
        <button type="button" disabled={busy || nothing} onClick={() => void save()} className="rounded-md bg-sky-600 px-3 py-1.5 text-sm text-white hover:bg-sky-500 disabled:opacity-40">
          {busy ? 'Saving...' : `Save ${ids.length} items`}
        </button>
      </div>
    </Modal>
  );
}

function SyncForm({ onDone, onClose }: { onDone: () => void; onClose: () => void }) {
  const [preview, setPreview] = useState<InventorySyncResult | null>(null);
  const [result, setResult] = useState<InventorySyncResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (dry: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const r = await inventoryApi.syncDevices(dry);
      if (dry) setPreview(r);
      else {
        setResult(r);
        onDone();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not read the device list.');
    } finally {
      setBusy(false);
    }
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => void run(true), []);
  const shown = result ?? preview;
  return (
    <Modal title="Add devices from NinjaOne and Addigy" onClose={onClose}>
      <p className="mb-3 text-xs text-gray-400">
        Windows computers, Macs, iPads and iPhones the tools report. One already in the inventory (same serial number) is matched and left alone. Any other is added as checked out at its client, because it is already out there.
      </p>
      {!shown && !error && <p className="text-sm text-gray-400">Reading the device list...</p>}
      {shown && (
        <div className="space-y-2 text-sm text-gray-200" data-testid={result ? 'sync-result' : 'sync-preview'}>
          <p>
            {shown.devices} devices reported ({Object.entries(shown.by_category).map(([c, n]) => `${n} ${c}`).join(', ') || 'none'}).
          </p>
          <p>
            {shown.matched} already in the inventory{shown.matched_in_stock > 0 ? `, ${shown.matched_in_stock} of them marked checked in although a tool reports them` : ''}.
          </p>
          <p>
            {result ? `Added ${shown.created} as checked out` : `${shown.created} would be added as checked out`}
            {shown.refreshed > 0 ? `, ${shown.refreshed} from an earlier sync ${result ? 'refreshed' : 'would be refreshed'}` : ''}.
          </p>
          {shown.no_serial > 0 && <p className="text-xs text-amber-300">{shown.no_serial} devices have no usable serial number, so they cannot be matched to a list item.</p>}
        </div>
      )}
      {error && (
        <p role="alert" className="mt-3 text-sm text-red-300">
          {error}
        </p>
      )}
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onClose} className={`${input} hover:bg-gray-800`}>
          {result ? 'Close' : 'Cancel'}
        </button>
        {!result && (
          <button type="button" disabled={busy || !preview || (preview.created === 0 && preview.refreshed === 0)} onClick={() => void run(false)} className="rounded-md bg-sky-600 px-3 py-1.5 text-sm text-white hover:bg-sky-500 disabled:opacity-40">
            {busy ? 'Working...' : 'Add them'}
          </button>
        )}
      </div>
    </Modal>
  );
}

function NucSyncForm({ onDone, onClose }: { onDone: () => void; onClose: () => void }) {
  const [preview, setPreview] = useState<InventoryNucSyncResult | null>(null);
  const [result, setResult] = useState<InventoryNucSyncResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (dry: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const r = await inventoryApi.syncNucs(dry);
      if (dry) setPreview(r);
      else {
        setResult(r);
        onDone();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not read the device list.');
    } finally {
      setBusy(false);
    }
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => void run(true), []);
  const shown = result ?? preview;
  return (
    <Modal title="Import NUCs from NinjaOne" onClose={onClose}>
      <p className="mb-3 text-xs text-gray-400">
        Looks at every NinjaOne device with NUC in its name. One already on this list (same serial number, same NinjaOne device, or the same name at the same client) is left alone. Any other is added under its client, as checked out, or as offline when NinjaOne has not seen it for a month.
      </p>
      {!shown && !error && <p className="text-sm text-gray-400">Reading the device list...</p>}
      {shown && (
        <div className="space-y-2 text-sm text-gray-200" data-testid={result ? 'nuc-result' : 'nuc-preview'}>
          <p>{shown.devices} NinjaOne devices have NUC in the name.</p>
          <p>{shown.matched} already on the list.</p>
          <p>{result ? `Added ${shown.created}` : `${shown.created} would be added`}{shown.no_serial > 0 ? `, ${shown.no_serial} with no usable serial number` : ''}.</p>
          {shown.names.length > 0 && <p className="text-xs text-gray-400">{result ? 'Added' : 'Would add'}: {shown.names.join(', ')}{shown.created > shown.names.length ? ', ...' : ''}</p>}
        </div>
      )}
      {error && (
        <p role="alert" className="mt-3 text-sm text-red-300">
          {error}
        </p>
      )}
      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onClose} className={`${input} hover:bg-gray-800`}>
          {result ? 'Close' : 'Cancel'}
        </button>
        {!result && (
          <button type="button" disabled={busy || !preview || preview.created === 0} onClick={() => void run(false)} className="rounded-md bg-sky-600 px-3 py-1.5 text-sm text-white hover:bg-sky-500 disabled:opacity-40">
            {busy ? 'Working...' : 'Add them'}
          </button>
        )}
      </div>
    </Modal>
  );
}

function SortHead({ label, field, sort, dir, onSort, className = 'px-3 py-2' }: { label: string; field: string; sort: string; dir: 'asc' | 'desc'; onSort: (f: string) => void; className?: string }) {
  const active = sort === field;
  return (
    <th className={className} aria-sort={active ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button type="button" onClick={() => onSort(field)} className="inline-flex items-center gap-1 uppercase hover:text-white" aria-label={`Sort by ${label}`}>
        {label}
        <span aria-hidden="true" className={active ? 'text-sky-300' : 'text-gray-600'}>{active ? (dir === 'asc' ? '▲' : '▼') : '↕'}</span>
      </button>
    </th>
  );
}

type Dialog = { type: 'add' } | { type: 'edit'; item: InventoryItem } | { type: 'out' | 'in'; item: InventoryItem } | { type: 'history'; item: InventoryItem } | { type: 'import' } | { type: 'bulk' } | { type: 'sync' } | { type: 'nucsync' } | null;

export function InventoryView() {
  const [kind, setKind] = useState<InventoryKind>('stock');
  const [client, setClient] = useState('');
  const [status, setStatus] = useState<InventoryStatus | ''>('');
  const [category, setCategory] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState('name');
  const [dir, setDir] = useState<'asc' | 'desc'>('asc');
  const [dialog, setDialog] = useState<Dialog>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const query: InventoryQuery = useMemo(
    () => ({ kind, client: client || undefined, status: status || undefined, category: category || undefined, search: search.trim() || undefined, page, pageSize: 100, sort, direction: dir }),
    [kind, client, status, category, search, page, sort, dir],
  );
  const { data, error, isLoading, mutate } = useSWR(['inventory', query], () => inventoryApi.list(query), { revalidateOnFocus: false, keepPreviousData: true });
  const { data: children } = useSWR('mssp-children', () => msspApi.listChildren().catch(() => []), { revalidateOnFocus: false });
  const clients: Clients = (children ?? []).map((c: { id: string; name: string }) => ({ id: c.id, name: c.name })).sort((a: { name: string }, b: { name: string }) => a.name.localeCompare(b.name));
  const reset = (fn: () => void) => {
    fn();
    setPage(1);
    setPicked(new Set());
  };
  const changed = () => {
    setDialog(null);
    setPicked(new Set());
    void mutate();
  };
  const onSort = (field: string) => {
    if (field === sort) setDir(dir === 'asc' ? 'desc' : 'asc');
    else {
      setSort(field);
      setDir('asc');
    }
    setPage(1);
  };
  const pageIds = (data?.items ?? []).map((i) => i.id);
  const allPicked = pageIds.length > 0 && pageIds.every((id) => picked.has(id));
  const toggle = (id: string) =>
    setPicked((p) => {
      const n = new Set(p);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const exportCsv = async () => {
    setExportError(null);
    try {
      const text = await inventoryApi.exportCsv(query);
      const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = `inventory-${kind}.csv`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setExportError(e instanceof Error ? e.message : 'Could not export the list.');
    }
  };
  const byStatus = data?.summary.by_status ?? {};
  return (
    <div className="space-y-4 p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-white">Inventory</h1>
          <p className="mt-1 text-sm text-gray-400">Stock we hold for clients, who has each item, and what has happened to it. Each item is filed under its client.</p>
        </div>
        <div className="flex gap-2">
          {kind === 'nuc' ? (
            <button type="button" onClick={() => setDialog({ type: 'nucsync' })} className={`${input} hover:bg-gray-800`}>
              Import NUCs from NinjaOne
            </button>
          ) : (
            <button type="button" onClick={() => setDialog({ type: 'sync' })} className={`${input} hover:bg-gray-800`}>
              Add devices from NinjaOne and Addigy
            </button>
          )}
          <button type="button" onClick={() => setDialog({ type: 'import' })} className={`${input} hover:bg-gray-800`}>
            Import CSV
          </button>
          <button type="button" onClick={() => void exportCsv()} className={`${input} hover:bg-gray-800`}>
            Export CSV
          </button>
          <button type="button" onClick={() => setDialog({ type: 'add' })} className="rounded-md bg-sky-600 px-3 py-1.5 text-sm text-white hover:bg-sky-500">
            {kind === 'nuc' ? 'Add a NUC' : 'Add an item'}
          </button>
        </div>
      </div>

      <div className="flex gap-1 border-b border-gray-800" role="tablist" aria-label="Inventory lists">
        {(['stock', 'nuc'] as InventoryKind[]).map((k) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={kind === k}
            onClick={() => reset(() => { setKind(k); setStatus(''); setCategory(''); setSort('name'); setDir('asc'); })}
            className={`px-4 py-2 text-sm ${kind === k ? 'border-b-2 border-sky-400 text-white' : 'text-gray-400 hover:text-white'}`}
          >
            {k === 'stock' ? 'Stock' : 'NUCs'}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap gap-2" data-testid="status-chips">
        {(Object.keys(STATUS_LABEL) as InventoryStatus[]).map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => reset(() => setStatus(status === s ? '' : s))}
            aria-pressed={status === s}
            className={`rounded-lg border px-3 py-1.5 text-sm ${status === s ? 'border-sky-500 bg-sky-500/10 text-white' : 'border-gray-800 bg-gray-900/60 text-gray-300 hover:border-gray-700'}`}
          >
            {STATUS_LABEL[s]} <span className="ml-1 font-semibold text-white">{byStatus[s] ?? 0}</span>
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <input type="search" aria-label="Search inventory" placeholder="Search name, serial, model, person or client" value={search} onChange={(e) => reset(() => setSearch(e.target.value))} className={`${input} w-72`} />
        <select aria-label="Client" value={client} onChange={(e) => reset(() => setClient(e.target.value))} className={input}>
          <option value="">All clients</option>
          <option value="own">Live Oak (own stock)</option>
          <option value="unmatched">Not matched to a client</option>
          {clients.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        {kind === 'stock' && (
          <select aria-label="Category" value={category} onChange={(e) => reset(() => setCategory(e.target.value))} className={input}>
            <option value="">Any category</option>
            {(data?.summary.categories ?? []).map(([c, n]) => (
              <option key={c} value={c}>
                {c} ({n})
              </option>
            ))}
          </select>
        )}
        {data && data.summary.unmatched_customers > 0 && (
          <span className="text-xs text-amber-300" title="Imported rows whose customer was not matched to a client are kept under Live Oak with the name as written. Edit an item to file it under a client.">
            {data.summary.unmatched_customers} customer names are not matched to a client
          </span>
        )}
      </div>
      {exportError && (
        <p role="alert" className="text-xs text-red-300">
          {exportError}
        </p>
      )}
      {error && (
        <p role="alert" className="rounded border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300">
          Could not load the inventory.
        </p>
      )}

      {picked.size > 0 && (
        <div className="flex items-center gap-3 rounded-lg border border-sky-500/40 bg-sky-500/10 px-3 py-2 text-sm text-white" data-testid="bulk-bar">
          <span>{picked.size} selected</span>
          <button type="button" onClick={() => setDialog({ type: 'bulk' })} className="rounded-md bg-sky-600 px-3 py-1 text-sm text-white hover:bg-sky-500">
            Edit selected
          </button>
          <button type="button" onClick={() => setPicked(new Set())} className="text-gray-300 hover:underline">
            Clear
          </button>
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-gray-800">
        <table className="w-full text-left text-sm" data-testid="inventory-table">
          <thead className="bg-gray-900 text-xs uppercase text-gray-400">
            <tr>
              <th className="w-8 px-3 py-2">
                <input type="checkbox" aria-label="Select all on this page" checked={allPicked} onChange={() => setPicked(allPicked ? new Set() : new Set(pageIds))} />
              </th>
              <SortHead label={kind === 'nuc' ? 'Computer' : 'Item'} field="name" sort={sort} dir={dir} onSort={onSort} />
              <SortHead label="Client" field="client" sort={sort} dir={dir} onSort={onSort} />
              <SortHead label="Serial" field="serial" sort={sort} dir={dir} onSort={onSort} />
              {kind === 'nuc' ? <SortHead label="Model" field="model" sort={sort} dir={dir} onSort={onSort} /> : <SortHead label="Category" field="category" sort={sort} dir={dir} onSort={onSort} />}
              {kind === 'stock' && <SortHead label="Qty" field="quantity" sort={sort} dir={dir} onSort={onSort} />}
              <SortHead label="Status" field="status" sort={sort} dir={dir} onSort={onSort} />
              <SortHead label={kind === 'nuc' ? 'Site and person' : 'With'} field={kind === 'nuc' ? 'site' : 'person'} sort={sort} dir={dir} onSort={onSort} />
              <SortHead label={kind === 'nuc' ? 'Deployed' : 'Last moved'} field="date" sort={sort} dir={dir} onSort={onSort} />
              <th className="px-3 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && !data && (
              <tr>
                <td colSpan={10} className="px-3 py-6 text-center text-gray-500">
                  Loading...
                </td>
              </tr>
            )}
            {data && data.items.length === 0 && (
              <tr>
                <td colSpan={10} className="px-3 py-6 text-center text-gray-500" data-testid="empty">
                  {data.summary.total === 0 && !search && !client ? 'Nothing here yet. Add an item, or import a SharePoint list with Import CSV.' : 'Nothing matches those filters.'}
                </td>
              </tr>
            )}
            {(data?.items ?? []).map((i) => (
              <tr key={i.id} className="border-t border-gray-800 align-top hover:bg-gray-900/40" data-testid="inventory-row">
                <td className="px-3 py-2">
                  <input type="checkbox" aria-label={`Select ${i.name}`} checked={picked.has(i.id)} onChange={() => toggle(i.id)} />
                </td>
                <td className="px-3 py-2">
                  <div className="font-medium text-gray-100">{i.name}</div>
                  {i.kind === 'stock' && i.model && i.model !== i.name && <div className="text-xs text-gray-500">{i.model}</div>}
                  {i.tags.length > 0 && <div className="mt-0.5 flex flex-wrap gap-1">{i.tags.map((t) => <span key={t} className="rounded bg-gray-800 px-1.5 text-[11px] text-gray-300">{t}</span>)}</div>}
                  {i.notes && <div className="mt-0.5 max-w-xs truncate text-xs text-gray-500" title={i.notes}>{i.notes}</div>}
                </td>
                <td className="px-3 py-2 text-gray-300">{holderLabel(i)}</td>
                <td className="px-3 py-2 font-mono text-xs text-gray-300">
                  {i.serial ?? '—'}
                  {i.device && (
                    <div className="font-sans">
                      <a href={`/devices?search=${encodeURIComponent(i.serial ?? i.device.hostname)}`} className="text-sky-300 hover:underline" title={`Seen ${safeDistance(i.device.last_seen, { addSuffix: true })}`} data-testid="device-link">
                        {i.device.hostname}
                      </a>
                    </div>
                  )}
                </td>
                <td className="px-3 py-2 text-gray-300">{kind === 'nuc' ? (i.model ?? '—') : (i.category ?? '—')}</td>
                {kind === 'stock' && <td className="px-3 py-2 text-gray-300">{i.quantity}</td>}
                <td className="px-3 py-2">
                  <span className={`rounded px-1.5 py-0.5 text-xs ${STATUS_STYLE[i.status]}`}>{STATUS_LABEL[i.status]}</span>
                </td>
                <td className="px-3 py-2 text-gray-300">{kind === 'nuc' ? [i.site, i.person].filter(Boolean).join(' · ') || '—' : [i.person, i.site].filter(Boolean).join(' · ') || '—'}</td>
                <td className="px-3 py-2 text-xs text-gray-400">{kind === 'nuc' ? dateText(i.redeployed_at ?? i.deployed_at) : dateText(i.status === 'checked_out' ? i.checked_out_at : i.checked_in_at)}</td>
                <td className="whitespace-nowrap px-3 py-2 text-right text-xs">
                  {(i.status === 'checked_in' || i.status === 'offline') && (
                    <button type="button" onClick={() => setDialog({ type: 'out', item: i })} className="mr-2 text-sky-300 hover:underline">
                      Check out
                    </button>
                  )}
                  {i.status === 'checked_out' && (
                    <button type="button" onClick={() => setDialog({ type: 'in', item: i })} className="mr-2 text-sky-300 hover:underline">
                      Check in
                    </button>
                  )}
                  <button type="button" onClick={() => setDialog({ type: 'edit', item: i })} className="mr-2 text-gray-300 hover:underline">
                    Edit
                  </button>
                  <button type="button" onClick={() => setDialog({ type: 'history', item: i })} className="text-gray-400 hover:underline">
                    History
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data && data.pages > 1 && (
        <div className="flex items-center justify-between text-sm text-gray-400">
          <span data-testid="count">
            {data.total} items · page {data.page} of {data.pages}
          </span>
          <div className="flex gap-2">
            <button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)} className="rounded border border-gray-700 px-3 py-1 disabled:opacity-40">
              Previous
            </button>
            <button type="button" disabled={page >= data.pages} onClick={() => setPage(page + 1)} className="rounded border border-gray-700 px-3 py-1 disabled:opacity-40">
              Next
            </button>
          </div>
        </div>
      )}
      {data && data.pages <= 1 && data.total > 0 && (
        <p className="text-sm text-gray-500" data-testid="count">
          {data.total} items
        </p>
      )}

      {dialog?.type === 'add' && <ItemForm kind={kind} clients={clients} onDone={changed} onClose={() => setDialog(null)} />}
      {dialog?.type === 'edit' && <ItemForm kind={dialog.item.kind} item={dialog.item} clients={clients} onDone={changed} onClose={() => setDialog(null)} />}
      {(dialog?.type === 'out' || dialog?.type === 'in') && <MoveForm item={dialog.item} mode={dialog.type} onDone={changed} onClose={() => setDialog(null)} />}
      {dialog?.type === 'bulk' && <BulkForm ids={[...picked]} clients={clients} onDone={changed} onClose={() => setDialog(null)} />}
      {dialog?.type === 'sync' && <SyncForm onDone={() => void mutate()} onClose={() => setDialog(null)} />}
      {dialog?.type === 'nucsync' && <NucSyncForm onDone={() => void mutate()} onClose={() => setDialog(null)} />}
      {dialog?.type === 'history' && <History item={dialog.item} onClose={() => setDialog(null)} />}
      {dialog?.type === 'import' && <ImportForm kind={kind} clients={clients} onDone={() => void mutate()} onClose={() => setDialog(null)} />}
    </div>
  );
}
