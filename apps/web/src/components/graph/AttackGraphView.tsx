'use client';

/**
 * Attack Graph + MITRE ATT&CK heatmap.
 *
 * Two stacked panels:
 *   1. Force-directed graph of hosts, users, IPs, processes, alerts and
 *      ATT&CK techniques, rendered with cytoscape.js + fcose layout.
 *   2. A live MITRE ATT&CK coverage heatmap (tactic columns x technique rows)
 *      with intensity shaded by detection count.
 *
 * Both panels are driven by `graphApi` and show only what it returns. If a call
 * fails the panel says so, with a Retry; if there is nothing yet it says that.
 * There is no sample data (a synthetic heatmap used to stand in for a failed
 * MITRE call, presenting invented coverage as the tenant's own).
 */

import Link from 'next/link';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import useSWR from 'swr';
import cytoscape, {
  type Core,
  type ElementDefinition,
  type NodeSingular,
} from 'cytoscape';
import fcose from 'cytoscape-fcose';
import { clsx } from 'clsx';
import {
  graphApi,
  type AttackGraph,
  type GraphNode,
  type GraphNodeKind,
  type MitreCoverage,
} from '@/lib/api';
import { Skeleton } from '@/components/ui/Skeleton';
import { ErrorState } from '@/components/ui/ErrorState';
import { EmptyState } from '@/components/ui/EmptyState';
import { ClientPicker } from '@/components/mssp/ClientPicker';
import { nodeLink } from './graphLinks';

// Register fcose once on the client.
if (typeof window !== 'undefined') {
  try {
    cytoscape.use(fcose as unknown as cytoscape.Ext);
  } catch {
    /* already registered (HMR) */
  }
}

const KIND_COLORS: Record<GraphNodeKind, string> = {
  host: '#60a5fa',
  user: '#a78bfa',
  ip: '#f59e0b',
  domain: '#fbbf24',
  hash: '#94a3b8',
  process: '#34d399',
  technique: '#f87171',
  tactic: '#fb7185',
  alert: '#ef4444',
  asset: '#22d3ee',
};

const KIND_SHAPES: Record<GraphNodeKind, string> = {
  host: 'round-rectangle',
  user: 'ellipse',
  ip: 'diamond',
  domain: 'diamond',
  hash: 'hexagon',
  process: 'round-tag',
  technique: 'round-pentagon',
  tactic: 'round-pentagon',
  alert: 'round-octagon',
  asset: 'round-rectangle',
};

const KIND_LABELS: Record<GraphNodeKind, string> = {
  host: 'Device',
  user: 'Identity',
  ip: 'IP address',
  domain: 'Domain',
  hash: 'File hash',
  process: 'Process',
  technique: 'ATT&CK technique',
  tactic: 'ATT&CK tactic',
  alert: 'Alert',
  asset: 'Asset',
};

/** The ring around a node says how serious the worst alert on it is. */
const SEVERITY_RING: Record<string, string> = {
  critical: '#f43f5e',
  high: '#fb923c',
  medium: '#facc15',
  low: '#38bdf8',
  info: '#64748b',
};

/** With this many nodes or fewer every name is shown; with more, only the serious ones, the one under the pointer and the neighbors of the selection (the rest would be a wall of text). */
const LABEL_ALL_UP_TO = 25;

// ─── Cytoscape canvas ─────────────────────────────────────────────────────────

interface GraphCanvasProps {
  graph: AttackGraph;
  selectedId: string | null;
  hiddenKinds: ReadonlySet<GraphNodeKind>;
  onSelect: (node: GraphNode | null) => void;
  /** Hands the page the drawing so its buttons (fit, zoom, re-arrange) can act on it. */
  onReady: (cy: Core | null) => void;
}

/** Fade everything except a node and what it touches (pure drawing change, no data). Pass null to show everything again. */
function focusOn(cy: Core, id: string | null): void {
  cy.elements().removeClass('faded').removeClass('near');
  if (!id) return;
  const node = cy.getElementById(id);
  if (node.empty()) return;
  const hood = node.closedNeighborhood();
  cy.elements().not(hood).addClass('faded');
  hood.addClass('near');
}

function GraphCanvas({ graph, selectedId, hiddenKinds, onSelect, onReady }: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const cyRef = useRef<Core | null>(null);
  const selectRef = useRef(onSelect);
  selectRef.current = onSelect;

  useEffect(() => {
    if (!containerRef.current) return;

    const showAll = graph.nodes.length <= LABEL_ALL_UP_TO;
    const elements: ElementDefinition[] = [
      ...graph.nodes.map((n) => ({
        data: {
          id: n.id,
          label: n.label.length > 28 ? `${n.label.slice(0, 27)}…` : n.label,
          kind: n.kind,
          color: KIND_COLORS[n.kind] ?? '#94a3b8',
          ring: SEVERITY_RING[n.severity ?? 'info'] ?? SEVERITY_RING.info,
          shape: KIND_SHAPES[n.kind] ?? 'ellipse',
          size: 26 + Math.min(34, (n.riskScore ?? 30) / 2.4),
        },
        classes: showAll || (n.riskScore ?? 0) >= 70 ? 'named' : '',
      })),
      ...graph.edges.map((e) => ({
        data: {
          id: e.id,
          source: e.source,
          target: e.target,
          label: e.label,
          w: 1 + Math.min(3, Math.log2(1 + (e.weight ?? 1))),
        },
      })),
    ];

    const cy = cytoscape({
      container: containerRef.current,
      elements,
      wheelSensitivity: 0.2,
      minZoom: 0.2,
      maxZoom: 3,
      style: [
        {
          selector: 'node',
          style: {
            'background-color': 'data(color)',
            'background-opacity': 0.92,
            shape: 'data(shape)' as cytoscape.Css.NodeShape,
            label: '',
            color: '#e2e8f0',
            'font-size': 11,
            'font-weight': 500,
            'font-family': 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto',
            'text-valign': 'bottom',
            'text-margin-y': 6,
            'text-outline-color': '#070d1a',
            'text-outline-width': 3,
            'text-max-width': '120px',
            'text-wrap': 'ellipsis',
            width: 'data(size)',
            height: 'data(size)',
            'border-color': 'data(ring)',
            'border-width': 3,
            'border-opacity': 0.95,
            'underlay-color': 'data(color)',
            'underlay-opacity': 0.14,
            'underlay-padding': 7,
            'underlay-shape': 'ellipse',
            'transition-property': 'opacity, underlay-opacity, border-width',
            'transition-duration': 150,
          } as cytoscape.Css.Node,
        },
        { selector: 'node.named, node.show, node.near', style: { label: 'data(label)' } },
        { selector: 'node.show', style: { 'underlay-opacity': 0.3 } },
        { selector: 'node:selected', style: { 'border-color': '#f8fafc', 'border-width': 4, 'underlay-opacity': 0.4, 'underlay-padding': 10 } },
        { selector: 'node.faded', style: { opacity: 0.14, label: '' } },
        {
          selector: 'edge',
          style: {
            width: 'data(w)',
            'line-color': '#334155',
            'line-opacity': 0.75,
            'target-arrow-color': '#334155',
            'target-arrow-shape': 'triangle',
            'arrow-scale': 0.8,
            'curve-style': 'bezier',
            label: '',
            'font-size': 9,
            color: '#94a3b8',
            'text-rotation': 'autorotate',
            'text-background-color': '#070d1a',
            'text-background-opacity': 0.85,
            'text-background-padding': '2px',
          } as cytoscape.Css.Edge,
        },
        { selector: 'edge.near', style: { 'line-color': '#7dd3fc', 'target-arrow-color': '#7dd3fc', 'line-opacity': 1, label: 'data(label)' } },
        { selector: 'edge.faded', style: { 'line-opacity': 0.05, 'target-arrow-shape': 'none' } },
      ],
      layout: {
        name: 'fcose',
        animate: true,
        animationDuration: 500,
        randomize: true,
        quality: 'default',
        nodeRepulsion: 14000,
        idealEdgeLength: 110,
        nodeSeparation: 90,
        gravity: 0.3,
        packComponents: true,
        padding: 40,
      } as unknown as cytoscape.LayoutOptions,
    });

    cy.on('tap', 'node', (evt) => {
      const node = evt.target as NodeSingular;
      selectRef.current(graph.nodes.find((n) => n.id === node.id()) ?? null);
    });
    cy.on('tap', (evt) => {
      if (evt.target === cy) selectRef.current(null);
    });
    // Names appear for the node under the pointer and what it touches, so a busy graph stays readable.
    cy.on('mouseover', 'node', (evt) => {
      const node = evt.target as NodeSingular;
      node.addClass('show');
      node.neighborhood('node').addClass('show');
      if (containerRef.current) containerRef.current.style.cursor = 'pointer';
    });
    cy.on('mouseout', 'node', () => {
      cy.nodes().removeClass('show');
      if (containerRef.current) containerRef.current.style.cursor = 'default';
    });

    cyRef.current = cy;
    onReady(cy);
    return () => {
      onReady(null);
      cy.destroy();
      cyRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph]);

  // The selection can also change from outside (a connection clicked in the side panel): show it here.
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().unselect();
    focusOn(cy, selectedId);
    if (selectedId) {
      const node = cy.getElementById(selectedId);
      if (!node.empty()) {
        node.select();
        cy.animate({ center: { eles: node }, duration: 250 });
      }
    }
  }, [selectedId, graph]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.nodes().forEach((n) => {
      n.style('display', hiddenKinds.has(n.data('kind') as GraphNodeKind) ? 'none' : 'element');
    });
  }, [hiddenKinds, graph]);

  return (
    <div
      ref={containerRef}
      className="h-full w-full"
      style={{ backgroundImage: 'radial-gradient(rgba(148,163,184,0.12) 1px, transparent 1px)', backgroundSize: '22px 22px' }}
    />
  );
}

/** What a selected node touches: each connection's name and kind, so the side panel can jump to it (pure). */
export function connectionsOf(graph: AttackGraph, id: string): GraphNode[] {
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const out = new Map<string, GraphNode>();
  for (const e of graph.edges) {
    const other = e.source === id ? e.target : e.target === id ? e.source : null;
    const node = other ? byId.get(other) : undefined;
    if (node) out.set(node.id, node);
  }
  return [...out.values()].sort((a, b) => (b.riskScore ?? 0) - (a.riskScore ?? 0) || a.label.localeCompare(b.label));
}

// ─── MITRE heatmap ────────────────────────────────────────────────────────────

function MitreHeatmap({ coverage }: { coverage: MitreCoverage }) {
  const grouped = useMemo(() => {
    const map = new Map<string, MitreCoverage['cells']>();
    for (const tactic of coverage.tactics) map.set(tactic, []);
    for (const cell of coverage.cells) {
      const list = map.get(cell.tactic) ?? [];
      list.push(cell);
      map.set(cell.tactic, list);
    }
    // Sort each column by intensity descending so the hot stuff bubbles up.
    for (const [k, v] of map)
      map.set(
        k,
        v.sort((a, b) => b.intensity - a.intensity),
      );
    return map;
  }, [coverage]);

  return (
    <div className="overflow-x-auto">
      <div
        className="grid gap-3 min-w-[1000px]"
        style={{
          gridTemplateColumns: `repeat(${coverage.tactics.length}, minmax(0, 1fr))`,
        }}
      >
        {coverage.tactics.map((tactic) => (
          <div key={tactic} className="flex flex-col gap-1">
            <div className="text-[10px] uppercase tracking-wider text-slate-400 mb-1 truncate">
              {tactic}
            </div>
            {(grouped.get(tactic) ?? []).map((cell) => {
              const a = 0.18 + cell.intensity * 0.72;
              return (
                <div
                  key={cell.techniqueId}
                  title={`${cell.techniqueId} ${cell.techniqueName} — ${cell.detections} detections / ${cell.alerts} alerts`}
                  className={clsx(
                    'rounded px-2 py-1.5 text-[10px] font-medium border border-white/5 hover:border-white/30 transition-colors cursor-default',
                    cell.detections === 0
                      ? 'text-slate-500'
                      : 'text-white',
                  )}
                  style={{
                    backgroundColor:
                      cell.detections === 0
                        ? 'rgba(148,163,184,0.05)'
                        : `rgba(239,68,68,${a})`,
                  }}
                >
                  <div className="truncate">{cell.techniqueId}</div>
                  <div className="truncate text-[9px] opacity-70">
                    {cell.techniqueName}
                  </div>
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

function SelectedPanel({ node, graph, client, onSelect }: { node: GraphNode; graph: AttackGraph | null; client: string; onSelect: (n: GraphNode | null) => void }) {
  const link = nodeLink(node, client);
  const connections = graph ? connectionsOf(graph, node.id) : [];
  const risk = node.riskScore ?? null;
  const ring = SEVERITY_RING[node.severity ?? 'info'] ?? SEVERITY_RING.info;
  return (
    <div className="space-y-4">
      <div>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 px-2 py-0.5 text-[10px] uppercase tracking-wider text-slate-300">
          <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: KIND_COLORS[node.kind] }} />
          {KIND_LABELS[node.kind] ?? node.kind}
        </span>
        <div className="mt-2 break-words text-base font-medium text-white">{node.label}</div>
      </div>
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-lg bg-slate-800/60 px-2.5 py-2">
          <div className="text-slate-500">Risk</div>
          <div className="font-medium text-white">{risk ?? '—'}</div>
          {risk !== null && (
            <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-slate-700" aria-hidden="true">
              <div className="h-full rounded-full" style={{ width: `${Math.min(100, risk)}%`, backgroundColor: ring }} />
            </div>
          )}
        </div>
        <div className="rounded-lg bg-slate-800/60 px-2.5 py-2">
          <div className="text-slate-500">Worst severity</div>
          <div className="flex items-center gap-1.5 font-medium capitalize text-white">
            <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: ring }} />
            {node.severity ?? '—'}
          </div>
        </div>
      </div>
      {typeof node.attributes?.alerts === 'number' && <p className="text-xs text-slate-400">{node.attributes.alerts} alert{node.attributes.alerts === 1 ? '' : 's'} name this.</p>}
      {link && (
        <Link href={link.href} className="block w-full rounded-lg bg-blue-500 px-3 py-2 text-center text-xs font-semibold text-white transition-colors hover:bg-blue-400">
          {link.label} →
        </Link>
      )}
      {connections.length > 0 && (
        <div>
          <h3 className="mb-1.5 text-[11px] uppercase tracking-wider text-slate-500">Connected to ({connections.length})</h3>
          <ul className="max-h-48 space-y-1 overflow-y-auto pr-1">
            {connections.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => onSelect(c)}
                  className="flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-xs text-slate-200 hover:bg-slate-800"
                >
                  <span className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: KIND_COLORS[c.kind] }} />
                  <span className="truncate">{c.label}</span>
                  <span className="ml-auto shrink-0 text-[10px] uppercase text-slate-500">{c.kind}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <button className="w-full rounded-lg border border-white/10 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800" onClick={() => onSelect(null)}>
        Clear selection
      </button>
    </div>
  );
}

// ─── Main view ────────────────────────────────────────────────────────────────

export function AttackGraphView() {
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [hiddenKinds, setHiddenKinds] = useState<ReadonlySet<GraphNodeKind>>(new Set());
  const cyRef = useRef<Core | null>(null);
  const onReady = useCallback((cy: Core | null) => {
    cyRef.current = cy;
  }, []);
  const toggleKind = (kind: GraphNodeKind) =>
    setHiddenKinds((old) => {
      const next = new Set(old);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
  // '' is the whole organization (every client together); an id is one client.
  const [client, setClient] = useState('');

  const graphState = useSWR<AttackGraph | null>(
    ['attack-graph', client],
    async (): Promise<AttackGraph | null> => {
      try {
        return await graphApi.getOverview({ depth: 3, ...(client ? { client } : {}) });
      } catch (err) {
        // The overview is built from alerts (GET /api/v1/graph). If the call fails, return null so the view says so instead of swallowing the error or inventing nodes.
        return null;
      }
    },
    { revalidateOnFocus: false, refreshInterval: 30_000 },
  );

  const mitreState = useSWR<MitreCoverage>(
    ['mitre-coverage', client],
    // A failure reaches the error state below (with a Retry). It used to be caught here and replaced with a synthetic heatmap of invented "Technique 3.2"
    // cells, so a failed call presented made-up coverage as the tenant's own.
    () => graphApi.getMitreCoverage(client ? { client } : {}),
    { revalidateOnFocus: false, refreshInterval: 60_000 },
  );

  const graph = graphState.data;
  const mitre = mitreState.data;

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-white">Attack Graph</h1>
            <p className="text-sm text-slate-400">
              Live identity, asset, and ATT&amp;CK relationships across your
              telemetry.
            </p>
          </div>
          <ClientPicker value={client} onChange={(id) => { setSelected(null); setClient(id); }} ownLabel="All clients" label="Client" />
          <div className="text-xs text-slate-500" suppressHydrationWarning>
            {graph
              ? `Generated ${new Date(graph.generatedAt).toLocaleTimeString()}`
              : ''}
          </div>
        </div>
      </header>

      {/* Graph panel */}
      <section className="rounded-xl bg-slate-900/60 border border-white/5 overflow-hidden">
        {!graph && (
          <div className="p-8 text-center space-y-3 border-b border-white/5">
            <h2 className="text-lg font-semibold text-gray-200">Attack Graph Unavailable</h2>
            <p className="text-sm text-gray-400 max-w-xl mx-auto">
              The graph overview (<code>GET /api/v1/graph</code>) did not load. If A.C.O.R.N was just rebuilt or restarted, reload in a minute; otherwise check
              Settings, Platform health for a service that is down.
            </p>
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-gray-800/60 text-xs text-gray-400 border border-gray-700">
              Could not load
            </span>
          </div>
        )}
        <div className="grid lg:grid-cols-[1fr_320px]">
          <div className="relative h-[560px] bg-[#0a1120]">
            {graphState.isLoading ? (
              <div className="p-6 space-y-3">
                <Skeleton className="h-4 w-40" />
                <Skeleton className="h-[480px] w-full rounded-lg" />
              </div>
            ) : graphState.error ? (
              <div className="p-6">
                <ErrorState
                  title="Couldn't load graph"
                  error={graphState.error}
                  onRetry={() => graphState.mutate()}
                />
              </div>
            ) : graph && graph.nodes.length > 0 ? (
              <GraphCanvas graph={graph} selectedId={selected?.id ?? null} hiddenKinds={hiddenKinds} onSelect={setSelected} onReady={onReady} />
            ) : (
              <div className="p-6">
                <EmptyState
                  title="No graph yet"
                  description="Entities and relationships appear here as events are ingested and alerts are fused."
                />
              </div>
            )}

            {/* Toolbar */}
            {graph && graph.nodes.length > 0 && (
              <div className="absolute right-3 top-3 flex flex-col gap-1.5">
                {[
                  { label: 'Zoom in', text: '+', run: (cy: Core) => cy.zoom({ level: cy.zoom() * 1.3, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } }) },
                  { label: 'Zoom out', text: '−', run: (cy: Core) => cy.zoom({ level: cy.zoom() / 1.3, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } }) },
                  { label: 'Fit the whole graph', text: '⤢', run: (cy: Core) => void cy.animate({ fit: { eles: cy.elements(':visible'), padding: 40 }, duration: 250 }) },
                  { label: 'Arrange again', text: '↻', run: (cy: Core) => void cy.layout({ name: 'fcose', animate: true, animationDuration: 500, randomize: true, nodeRepulsion: 14000, idealEdgeLength: 110, nodeSeparation: 90, packComponents: true, padding: 40 } as unknown as cytoscape.LayoutOptions).run() },
                ].map((b) => (
                  <button
                    key={b.label}
                    type="button"
                    aria-label={b.label}
                    title={b.label}
                    onClick={() => cyRef.current && b.run(cyRef.current)}
                    className="h-8 w-8 rounded-lg border border-white/10 bg-slate-900/85 text-sm text-slate-200 backdrop-blur-sm transition-colors hover:bg-slate-800"
                  >
                    {b.text}
                  </button>
                ))}
              </div>
            )}

            {/* Legend: click a kind to hide or show it */}
            <div className="absolute bottom-3 left-3 flex flex-wrap gap-1.5 rounded-xl border border-white/10 bg-slate-900/85 p-2 backdrop-blur-sm" role="group" aria-label="Show or hide kinds">
              {(['host', 'user', 'ip', 'process', 'technique', 'alert'] as GraphNodeKind[]).map((kind) => {
                const off = hiddenKinds.has(kind);
                return (
                  <button
                    key={kind}
                    type="button"
                    aria-pressed={!off}
                    onClick={() => toggleKind(kind)}
                    title={off ? `Show ${KIND_LABELS[kind]}` : `Hide ${KIND_LABELS[kind]}`}
                    className={clsx(
                      'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wider transition-colors',
                      off ? 'border-white/5 text-slate-500 line-through' : 'border-white/10 text-slate-200 hover:bg-white/5',
                    )}
                  >
                    <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ backgroundColor: off ? '#475569' : KIND_COLORS[kind] }} />
                    {kind}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Side panel */}
          <aside className="border-l border-white/5 bg-slate-900/80 p-4 text-sm" data-testid="graph-side-panel">
            <h2 className="mb-3 text-xs uppercase tracking-wider text-slate-400">{selected ? 'Selected entity' : 'How to read this'}</h2>
            {selected ? (
              <SelectedPanel node={selected} graph={graph ?? null} client={client} onSelect={setSelected} />
            ) : (
              <ul className="space-y-2 text-xs leading-relaxed text-slate-400">
                <li>
                  <span className="font-medium text-white">Click</span> a node to see its risk, what it connects to, and a button to open the device, identity or alert behind it.
                </li>
                <li>The ring around a node is the worst alert severity on it; bigger means higher risk. Point at a node to see its name and its neighbors.</li>
                <li>Click a kind at the bottom left to hide or show it. The graph refreshes every 30 seconds.</li>
              </ul>
            )}
          </aside>
        </div>
      </section>

      {/* MITRE heatmap */}
      <section className="rounded-xl bg-slate-900/60 border border-white/5 p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-white">
              MITRE ATT&amp;CK Coverage
            </h2>
            <p className="text-xs text-slate-400">
              Detection density across tactics. Brighter cells mean more
              detections firing on that technique.
            </p>
          </div>
          <div className="text-xs text-slate-500" suppressHydrationWarning>
            {mitre
              ? `Updated ${new Date(mitre.generatedAt).toLocaleTimeString()}`
              : ''}
          </div>
        </div>

        {mitreState.isLoading ? (
          <Skeleton className="h-64 w-full rounded-lg" />
        ) : mitreState.error ? (
          <ErrorState
            title="Couldn't load MITRE coverage"
            error={mitreState.error}
            onRetry={() => mitreState.mutate()}
          />
        ) : mitre && mitre.cells.length > 0 ? (
          <MitreHeatmap coverage={mitre} />
        ) : (
          <EmptyState
            title="No coverage data"
            description="Once detections start firing, this heatmap lights up by tactic."
          />
        )}
      </section>
    </div>
  );
}
