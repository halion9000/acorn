'use client';

/**
 * PlaybooksView
 * =============
 * /playbooks page — lists all playbooks with quick-run/edit/delete,
 * a Run History tab and a Dry Runs tab.
 *
 * WS-F3: SavedViewsBar wired to the Playbooks tab so analysts can save and
 * recall filter presets (source, category, MITRE tactic, severity, integration,
 * and search query).
 *
 * Author: Beenu <beenu@cyble.com>
 */

import React, { useState, useCallback, useEffect } from 'react';
import Link from 'next/link';
import useSWR from 'swr';
import clsx from 'clsx';
import type { Playbook, PlaybookRun } from './types';
import { PlaybooksGallery, type PlaybookGalleryFilters } from './PlaybooksGallery';
import { EmptyState, EmptyStateIcons } from '@/components/ui/EmptyState';
import { ErrorState } from '@/components/ui/ErrorState';
import { SavedViewsBar } from '@/components/saved-views/SavedViewsBar';
import { DraftFromPromptDialog } from './DraftFromPromptDialog';
import { authFetch } from '@/lib/auth-session';
import { DryRunsTab } from './DryRuns';
import { RunLog } from './RunLog';

/** Filter snapshot stored by the backend as a saved-view preset. */
type PlaybookFilterSnapshot = PlaybookGalleryFilters;

const DEFAULT_PLAYBOOK_FILTERS: PlaybookFilterSnapshot = {
  source: 'all',
  category: 'all',
  mitreTactic: 'all',
  severity: 'all',
  integration: 'all',
  search: '',
};

const fetcher = (url: string) =>
  authFetch(url).then((r) => {
    if (!r.ok) throw new Error('Failed to fetch');
    return r.json();
  });

/* ─────────────────────────── Run History Tab ─────────────────────────── */

function RunHistoryTab() {
  const { data, isLoading, error } = useSWR<PlaybookRun[]>(
    '/api/v1/playbooks/runs?limit=100',
    fetcher,
    { refreshInterval: 10000 }
  );
  if (isLoading) return <div className="py-10 text-center text-gray-600 text-sm">Loading run history…</div>;
  if (error) return (
    <div className="rounded-md border border-amber-500/30 bg-amber-500/5 px-4 py-2 text-xs text-amber-200">
      Run history unavailable — the agents service may be offline.
    </div>
  );
  if (!data || data.length === 0)
    // WS-F5 — fresh tenants haven't run anything yet; nudge toward the editor.
    return (
      <EmptyState
        icon={EmptyStateIcons.ledger}
        title="No playbook runs yet"
        description="Run history shows up after you trigger a playbook — either manually from the editor's dry-run button, or automatically when an alert matches a playbook trigger."
        className="bg-transparent py-12"
      />
    );
  return <RunLog runs={data} />;
}

/* ─────────────────────────── Main ─────────────────────────── */

export function PlaybooksView() {
  const [tab, setTab] = useState<'playbooks' | 'runs' | 'dryruns'>('playbooks');
  const { data, isLoading, error, mutate } = useSWR<Playbook[]>('/api/v1/playbooks', fetcher, {
    refreshInterval: 30000,
  });

  // WS-F3: track the active filter snapshot so SavedViewsBar can capture it,
  // and force-remount PlaybooksGallery when a preset is applied so the gallery
  // picks up the new initial state without requiring full controlled-prop surgery.
  const [galleryFilters, setGalleryFilters] = useState<PlaybookFilterSnapshot>(DEFAULT_PLAYBOOK_FILTERS);
  const [galleryKey, setGalleryKey] = useState(0);

  // T3.7 — controls the NL → playbook drafter modal. The modal posts to
  // /api/v1/playbooks/draft-from-nl, parks the draft in sessionStorage,
  // then routes to /playbooks/new where the editor picks it up.
  const [nlDialogOpen, setNlDialogOpen] = useState(false);

  function handleApplyView(filters: PlaybookFilterSnapshot) {
    setGalleryFilters(filters);
    setGalleryKey((k) => k + 1);
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Playbooks</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Automated response workflows triggered by alerts and cases
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setNlDialogOpen(true)}
            className="px-4 py-2 rounded-lg border border-blue-600/60 bg-blue-950/40 text-blue-300 hover:bg-blue-900/40 hover:text-blue-200 text-sm font-medium transition-colors"
            title="T3.7 — describe a playbook in natural language and A.C.O.R.N drafts the DAG."
          >
            ✨ Draft from prompt
          </button>
          <Link
            href="/playbooks/new"
            className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors"
          >
            + New Playbook
          </Link>
        </div>
      </div>

      <DraftFromPromptDialog open={nlDialogOpen} onClose={() => setNlDialogOpen(false)} />

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-800/60">
        <button
          onClick={() => setTab('playbooks')}
          className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${tab === 'playbooks' ? 'border-blue-500 text-blue-300' : 'border-transparent text-gray-500 hover:text-gray-300'}`}
        >
          Playbooks ({data?.length ?? '…'})
        </button>
        <button
          onClick={() => setTab('runs')}
          className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${tab === 'runs' ? 'border-blue-500 text-blue-300' : 'border-transparent text-gray-500 hover:text-gray-300'}`}
        >
          Run History
        </button>
        <button
          onClick={() => setTab('dryruns')}
          className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${tab === 'dryruns' ? 'border-blue-500 text-blue-300' : 'border-transparent text-gray-500 hover:text-gray-300'}`}
        >
          Dry Runs
        </button>
      </div>

      {/* Run History */}
      {tab === 'runs' && <RunHistoryTab />}

      {/* Dry runs: which playbooks would have run for which alerts (nothing is run) */}
      {tab === 'dryruns' && <DryRunsTab />}


      {/* Playbooks list */}
      {tab === 'playbooks' && (
        <>
          {/* WS-F3: saved-view presets for the playbooks list */}
          <SavedViewsBar<PlaybookFilterSnapshot>
            viewType="playbooks"
            filters={galleryFilters}
            onApply={handleApplyView}
          />

          {isLoading && <div className="text-gray-600 text-sm">Loading playbooks…</div>}

          {/* There are no demo playbooks: the old banner said "showing demo playbooks so you can explore the workflow", which was never true. */}
          {error && !data && (
            <ErrorState
              title="Couldn't load playbooks"
              description="The agents service didn't respond."
              error={error}
              onRetry={() => void mutate()}
            />
          )}
          {error && data && (
            <div role="alert" className="rounded-md border border-amber-500/30 bg-amber-500/5 px-4 py-2 text-xs text-amber-200">
              Couldn&rsquo;t refresh playbooks; showing what was last loaded.
            </div>
          )}

          {!isLoading && !error && (!data || data.length === 0) && (
            // WS-F5 — first-run experience. Push toward both "create your own"
            // and the shared library so analysts don't have to start from
            // a blank YAML file.
            <EmptyState
              icon={EmptyStateIcons.ledger}
              title="No playbooks yet"
              description="Playbooks automate your SOC response — isolate hosts, enrich IOCs, page on-call, post to Slack. Start from a shipped library playbook or write your own from scratch."
              action={
                <div className="flex items-center gap-2">
                  <Link
                    href="/playbooks/new"
                    className="px-3 py-1.5 rounded-md bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium transition-colors"
                  >
                    Create your first playbook
                  </Link>
                </div>
              }
              className="bg-transparent py-16"
            />
          )}

          {/* key forces remount when a saved preset is applied, seeding gallery
              state from the preset's filter snapshot without full prop-drilling. */}
          {data && data.length > 0 && (
            <PlaybooksGallery
              key={galleryKey}
              playbooks={data}
              initialFilters={galleryFilters}
            />
          )}
        </>
      )}
    </div>
  );
}
