/**
 * SOC Insights dashboard view (T3.1).
 *
 * Owns the data-fetching + layout for the 7-tile grid. Split out of
 * the route file so the page module can stay a pure server component
 * (per Next.js App Router conventions); this file is the "use client"
 * boundary.
 */
'use client';

import { useEffect, useMemo, useState } from 'react';
import useSWR from 'swr';

import { useRealtimeChannel } from '@/lib/realtime';
import {
  type InsightTile,
  type InsightsWindow,
  type SOCInsightsResponse,
  insightsApi,
  msspApi,
} from '@/lib/api';

import { InsightTileCard } from './InsightTileCard';
import { Sparkline } from './Sparkline';

const WINDOW_OPTIONS: InsightsWindow[] = ['24h', '7d', '30d'];

interface RealtimePoke {
  type: string;
  reason?: string;
  timestamp?: string;
}

export function SOCInsightsView() {
  const [window, setWindow] = useState<InsightsWindow>('24h');
  const [clientId, setClientId] = useState('');
  // The organization's clients, for the picker. An organization with none (or a call that fails) just has no picker.
  const { data: clients } = useSWR('insights:clients', () => msspApi.listChildren().catch(() => []), { revalidateOnFocus: false });

  const { data, error, isLoading, mutate } = useSWR<SOCInsightsResponse>(
    ['insights:soc', window, clientId],
    () => insightsApi.getSOC(window, clientId || undefined),
    {
      // The realtime channel pokes us every 30s; we also revalidate
      // on focus in case the tab was backgrounded long enough for
      // the WebSocket to disconnect.
      revalidateOnFocus: true,
      revalidateIfStale: true,
      // Don't dedupe identical-key refetches — the realtime poke is
      // explicit "go look again", we want it honoured even if SWR
      // just fetched.
      dedupingInterval: 0,
    },
  );

  // Subscribe to `insights_updated` events from the realtime service.
  // The hook keeps the socket alive and reconnects with exponential
  // backoff; we just react to the last received frame.
  const { last } = useRealtimeChannel<RealtimePoke>('insights');

  useEffect(() => {
    if (last?.type === 'insights_updated' || last?.type === 'case.updated') {
      // Ask again, keeping what is on screen until the new numbers arrive. (mutate(undefined, ...) used to be here: it sets the cached data to
      // undefined, so every poke blanked the page to its loading outline for as long as the API took to answer.)
      void mutate();
    }
  }, [last, mutate]);

  return (
    <div className="space-y-6 p-6">
      <Header
        window={window}
        onWindowChange={setWindow}
        generatedAt={data?.generated_at}
        manualMinutes={data?.manual_investigation_minutes}
        comparisonReady={data?.comparison_ready}
        historySince={data?.history_since}
        clients={(clients ?? []).map((c) => ({ id: c.id, name: c.name }))}
        clientId={clientId}
        onClientChange={setClientId}
      />

      {error ? (
        <ErrorState
          message={error instanceof Error ? error.message : String(error)}
          onRetry={() => mutate()}
        />
      ) : isLoading || !data ? (
        <LoadingSkeleton />
      ) : (
        <TileGrid tiles={data.tiles} clientId={clientId || undefined} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Subcomponents
// ---------------------------------------------------------------------------

interface HeaderProps {
  window: InsightsWindow;
  onWindowChange: (w: InsightsWindow) => void;
  generatedAt: string | undefined;
  manualMinutes: number | undefined;
  comparisonReady: boolean | undefined;
  historySince: string | null | undefined;
  clients: { id: string; name: string }[];
  clientId: string;
  onClientChange: (id: string) => void;
}

function Header({ window, onWindowChange, generatedAt, manualMinutes, comparisonReady, historySince, clients, clientId, onClientChange }: HeaderProps) {
  const stamp = useMemo(() => {
    if (!generatedAt) return null;
    try {
      return new Date(generatedAt).toLocaleTimeString();
    } catch {
      return generatedAt;
    }
  }, [generatedAt]);

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">SOC Insights</h1>
        <p className="mt-1 max-w-prose text-sm text-muted-foreground">
          Operational tiles for the SOC, refreshed every 30 seconds and
          on case changes. Deltas compare against the immediately preceding
          window. Hours-saved assumes {manualMinutes ?? 45} minutes of analyst
          time per auto-closed case. Click a tile to see what is behind it.
        </p>
        {comparisonReady === false ? (
          <p className="mt-2 max-w-prose text-sm text-muted-foreground" data-testid="insights-history-note">
            Change figures are hidden until there is a full earlier {window === '24h' ? 'day' : window === '7d' ? 'week' : 'month'} of data to compare with
            {historySince ? ` (the first alert was recorded ${new Date(historySince).toLocaleDateString()})` : ''}.
          </p>
        ) : null}
      </div>
      <div className="flex items-center gap-4">
        {stamp ? (
          <span className="text-xs text-muted-foreground" aria-live="polite">
            Updated {stamp}
          </span>
        ) : null}
        {clients.length > 0 ? (
          <select
            aria-label="Client"
            value={clientId}
            onChange={(e) => onClientChange(e.target.value)}
            className="rounded-md border border-border bg-card px-2 py-1 text-xs"
          >
            <option value="">All clients</option>
            {[...clients].sort((a, b) => a.name.localeCompare(b.name)).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        ) : null}
        <WindowSelector value={window} onChange={onWindowChange} />
      </div>
    </div>
  );
}

interface WindowSelectorProps {
  value: InsightsWindow;
  onChange: (w: InsightsWindow) => void;
}

function WindowSelector({ value, onChange }: WindowSelectorProps) {
  return (
    <div
      role="radiogroup"
      aria-label="Window"
      className="inline-flex rounded-md border border-border bg-card p-0.5 text-xs"
    >
      {WINDOW_OPTIONS.map((option) => {
        const active = option === value;
        return (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(option)}
            className={
              active
                ? 'rounded bg-primary px-3 py-1 font-medium text-primary-foreground'
                : 'rounded px-3 py-1 text-muted-foreground hover:text-foreground'
            }
          >
            {option}
          </button>
        );
      })}
    </div>
  );
}

interface TileGridProps {
  tiles: InsightTile[];
  clientId?: string;
}

function TileGrid({ tiles, clientId }: TileGridProps) {
  return (
    <div
      // the tiles fit as a 4-wide grid at lg, 2-wide at md, 1 per
      // row on phones. The grid keeps a constant ratio so the
      // sparkline width doesn't jump between window changes.
      className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
      data-testid="soc-insights-tiles"
    >
      {tiles.map((tile) => (
        <InsightTileCard
          key={tile.key}
          tile={tile}
          clientId={clientId}
          sparkline={<Sparkline points={tile.sparkline.points} />}
        />
      ))}
    </div>
  );
}

// About as many outlines as there are tiles (the API sends 14 or 15), so the page does not jump when they arrive.
const LOADING_TILES = 14;

function LoadingSkeleton() {
  // Skeleton tiles arranged on the same grid. The fixed heights
  // mean the layout doesn't reflow when the real data arrives.
  return (
    <div
      className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
      aria-busy="true"
      aria-label="Loading SOC insights"
    >
      {Array.from({ length: LOADING_TILES }).map((_, i) => (
        <div
          key={i}
          className="h-32 animate-pulse rounded-lg border border-border bg-card"
        />
      ))}
    </div>
  );
}

interface ErrorStateProps {
  message: string;
  onRetry: () => void;
}

function ErrorState({ message, onRetry }: ErrorStateProps) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-destructive/30 bg-destructive/5 p-6 text-sm"
    >
      <p className="font-medium text-destructive">
        SOC Insights are temporarily unavailable.
      </p>
      <p className="mt-1 text-muted-foreground">{message}</p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-3 rounded border border-border bg-background px-3 py-1.5 text-xs font-medium hover:bg-muted"
      >
        Retry
      </button>
    </div>
  );
}
