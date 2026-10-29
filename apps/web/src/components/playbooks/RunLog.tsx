'use client';

/**
 * The playbook run log: every run the agents service has recorded, one playbook at a time when one is picked, each run expandable to its steps with their times, errors and output. Read only.
 */
import { useMemo, useState } from 'react';
import type { PlaybookRun, PlaybookRunStep } from './types';

export interface PlaybookChoice {
  id: string;
  name: string;
  runs: number;
  failed: number;
}

/** The playbooks that have runs, by name, with how many runs and how many of them failed. */
export function playbookChoices(runs: PlaybookRun[]): PlaybookChoice[] {
  const by = new Map<string, PlaybookChoice>();
  for (const r of runs) {
    const row = by.get(r.playbook_id) ?? { id: r.playbook_id, name: r.playbook_name, runs: 0, failed: 0 };
    row.runs++;
    if (r.status === 'failed') row.failed++;
    by.set(r.playbook_id, row);
  }
  return [...by.values()].sort((a, b) => a.name.localeCompare(b.name));
}

/** The runs of one playbook (or all of them when none is picked), newest first. */
export function runsFor(runs: PlaybookRun[], playbookId: string): PlaybookRun[] {
  return runs
    .filter((r) => !playbookId || r.playbook_id === playbookId)
    .sort((a, b) => Date.parse(b.started_at ?? '') - Date.parse(a.started_at ?? '') || 0);
}

/** "12 s", "3 min 5 s" or "" when the run has not both started and finished. */
export function durationText(startedAt?: string, completedAt?: string): string {
  const a = Date.parse(startedAt ?? '');
  const b = Date.parse(completedAt ?? '');
  if (Number.isNaN(a) || Number.isNaN(b) || b < a) return '';
  const secs = Math.round((b - a) / 1000);
  if (secs < 60) return `${secs} s`;
  return `${Math.floor(secs / 60)} min${secs % 60 ? ` ${secs % 60} s` : ''}`;
}

/** What a step produced, short enough to show: strings as they are, other values as JSON, cut at 300 characters. */
export function outputText(output: unknown): string {
  if (output === undefined || output === null || output === '') return '';
  const text = typeof output === 'string' ? output : JSON.stringify(output);
  return text.length > 300 ? `${text.slice(0, 299)}…` : text;
}

/** "3 of 8 runs failed" (or nothing when none did) for the picked playbook. */
export function failureLine(choice: PlaybookChoice | undefined): string {
  if (!choice || choice.failed === 0) return '';
  return `${choice.failed} of ${choice.runs} run${choice.runs === 1 ? '' : 's'} failed`;
}

const STATUS_BADGE: Record<string, string> = {
  pending: 'bg-yellow-900/40 text-yellow-400 border-yellow-800',
  running: 'bg-blue-900/40 text-blue-400 border-blue-800',
  completed: 'bg-green-900/40 text-green-400 border-green-800',
  failed: 'bg-red-900/40 text-red-400 border-red-800',
  cancelled: 'bg-gray-800 text-gray-500 border-gray-700',
};

function Steps({ steps }: { steps: PlaybookRunStep[] }) {
  return (
    <ol className="mt-2 space-y-1 border-t border-gray-800 pt-2 text-xs" data-testid="run-steps">
      {steps.map((s) => {
        const out = outputText(s.output);
        return (
          <li key={s.step_id} className="text-gray-300">
            <span className="font-medium">{s.step_name}</span> <span className="text-gray-500">{s.status}</span>
            {durationText(s.started_at, s.completed_at) && <span className="text-gray-600"> · {durationText(s.started_at, s.completed_at)}</span>}
            {s.error && <span className="block text-red-300">{s.error}</span>}
            {out && <span className="block break-words font-mono text-gray-500">{out}</span>}
          </li>
        );
      })}
    </ol>
  );
}

export function RunLog({ runs }: { runs: PlaybookRun[] }) {
  const [playbookId, setPlaybookId] = useState('');
  const [open, setOpen] = useState<Set<string>>(new Set());
  const choices = useMemo(() => playbookChoices(runs), [runs]);
  const shown = useMemo(() => runsFor(runs, playbookId), [runs, playbookId]);
  const picked = choices.find((c) => c.id === playbookId);
  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3 text-xs text-gray-400">
        <select aria-label="Playbook" value={playbookId} onChange={(e) => setPlaybookId(e.target.value)} className="rounded border border-gray-700 bg-gray-900 px-2 py-1 text-gray-200">
          <option value="">All playbooks ({runs.length} runs)</option>
          {choices.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} ({c.runs})
            </option>
          ))}
        </select>
        {failureLine(picked) && (
          <span data-testid="run-failures" className="text-red-300">
            {failureLine(picked)}
          </span>
        )}
      </div>
      {shown.map((run) => {
        const isOpen = open.has(run.run_id);
        return (
          <div key={run.run_id} className="bg-gray-900/60 border border-gray-800 rounded-xl px-5 py-3">
            <div className="flex items-center gap-4">
              <span className={`text-xs px-2 py-0.5 rounded border ${STATUS_BADGE[run.status] ?? 'bg-gray-800 text-gray-400 border-gray-700'}`}>{run.status}</span>
              <div className="flex-1 min-w-0">
                <div className="text-white text-sm font-medium truncate">{run.playbook_name}</div>
                <div className="flex items-center gap-3 mt-0.5 text-xs text-gray-600">
                  <span className="font-mono">{run.run_id.slice(0, 12)}…</span>
                  <span>{run.steps.length} steps</span>
                  {run.dry_run && <span className="text-yellow-700 border border-yellow-900 px-1.5 rounded">dry run</span>}
                  {run.started_at && <span suppressHydrationWarning>{new Date(run.started_at).toLocaleString()}</span>}
                  {durationText(run.started_at, run.completed_at) && <span>{durationText(run.started_at, run.completed_at)}</span>}
                </div>
              </div>
              <div className="flex items-center gap-1">
                {run.steps.slice(0, 8).map((s) => {
                  const dot =
                    s.status === 'completed' ? 'bg-green-500' : s.status === 'failed' ? 'bg-red-500' : s.status === 'running' ? 'bg-blue-400 animate-pulse' : s.status === 'skipped' ? 'bg-gray-700' : 'bg-gray-800';
                  return <div key={s.step_id} className={`w-2 h-2 rounded-full ${dot}`} title={`${s.step_name}: ${s.status}`} />;
                })}
                {run.steps.length > 8 && <span className="text-xs text-gray-700">+{run.steps.length - 8}</span>}
              </div>
              <button type="button" aria-expanded={isOpen} aria-label={`${isOpen ? 'Hide' : 'Show'} steps of run ${run.run_id.slice(0, 12)}`} onClick={() => toggle(run.run_id)} className="text-xs text-blue-300 hover:text-blue-200">
                {isOpen ? 'Hide steps' : 'Steps'}
              </button>
            </div>
            {isOpen && <Steps steps={run.steps} />}
          </div>
        );
      })}
    </div>
  );
}
