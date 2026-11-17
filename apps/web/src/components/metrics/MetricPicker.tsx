'use client';

/**
 * Choosing which team members, items or roles a Metrics table shows: one button that says how many are shown, which opens a panel with a search box, Select all, Clear and a scrolling list of
 * boxes. It replaces the wall of check boxes that made these pages unreadable when there were hundreds of choices. The pure helpers are tested on their own.
 */
import { useEffect, useRef, useState } from 'react';

export interface PickOption {
  value: string;
  label: string;
  /** A short note after the label (a count, the tool it comes from). */
  hint?: string;
}

/** The options whose label or note holds every word typed (letter case ignored); all of them for no text (pure). */
export function filterOptions(options: PickOption[], query: string): PickOption[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return options;
  return options.filter((o) => words.every((w) => `${o.label} ${o.hint ?? ''}`.toLowerCase().includes(w)));
}

/** "All 47 team members", "3 of 47 team members" or "No team members" (pure). */
export function pickerSummary(selected: number, total: number, noun: string): string {
  if (total === 0) return `No ${noun}`;
  if (selected >= total) return `All ${total} ${noun}`;
  if (selected === 0) return `No ${noun} shown`;
  return `${selected} of ${total} ${noun}`;
}

/** The selection after Select all (the matches are added) or Clear (the matches are taken out); with no search the matches are everything (pure). */
export function applyToMatches(selected: string[], matches: PickOption[], on: boolean): string[] {
  const ids = new Set(matches.map((m) => m.value));
  if (on) return [...new Set([...selected, ...ids])];
  return selected.filter((s) => !ids.has(s));
}

export function MetricPicker({ noun, options, selected, onChange }: { noun: string; options: PickOption[]; selected: string[]; onChange: (next: string[]) => void }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', away);
    document.addEventListener('keydown', key);
    return () => {
      document.removeEventListener('mousedown', away);
      document.removeEventListener('keydown', key);
    };
  }, [open]);
  const matches = filterOptions(options, query);
  const chosen = new Set(selected);
  const toggle = (v: string) => onChange(chosen.has(v) ? selected.filter((s) => s !== v) : [...selected, v]);
  return (
    <div ref={box} className="relative inline-block" data-testid="metric-picker">
      <button type="button" aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen((o) => !o)} className="rounded border border-gray-700 bg-gray-900 px-3 py-1.5 text-sm text-gray-100 hover:bg-gray-800">
        {pickerSummary(selected.length, options.length, noun)} <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <div role="dialog" aria-label={`Choose ${noun}`} className="absolute left-0 z-20 mt-1 w-80 max-w-[90vw] rounded-lg border border-gray-700 bg-gray-900 p-3 shadow-xl">
          <input aria-label={`Search ${noun}`} autoFocus type="search" placeholder={`Search ${noun}…`} value={query} onChange={(e) => setQuery(e.target.value)} className="w-full rounded border border-gray-700 bg-gray-950 px-2 py-1 text-sm text-gray-100" />
          <div className="mt-2 flex items-center gap-3 text-xs">
            <button type="button" className="text-blue-300 hover:underline" onClick={() => onChange(applyToMatches(selected, matches, true))}>
              Select all{query.trim() ? ' matching' : ''}
            </button>
            <button type="button" className="text-blue-300 hover:underline" onClick={() => onChange(applyToMatches(selected, matches, false))}>
              Clear{query.trim() ? ' matching' : ''}
            </button>
            <span className="flex-1" />
            <span className="text-gray-500">{matches.length} shown</span>
          </div>
          <ul className="mt-2 max-h-64 space-y-0.5 overflow-y-auto pr-1" aria-label={noun}>
            {matches.map((o) => (
              <li key={o.value}>
                <label className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-sm text-gray-200 hover:bg-gray-800">
                  <input type="checkbox" checked={chosen.has(o.value)} onChange={() => toggle(o.value)} />
                  <span className="min-w-0 flex-1 truncate">{o.label}</span>
                  {o.hint ? <span className="text-xs text-gray-500">{o.hint}</span> : null}
                </label>
              </li>
            ))}
            {matches.length === 0 && <li className="px-1 py-2 text-xs text-gray-500">Nothing matches.</li>}
          </ul>
        </div>
      )}
    </div>
  );
}
