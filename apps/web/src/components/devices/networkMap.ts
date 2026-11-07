/**
 * Lays one client's network out as a drawing: internet-facing gear at the top, then switches, then access points, then everything plugged into them.
 * Pure (no React), so the layout is tested without a browser. Input is the environment's devices; a link names its neighbour by device name (that is what Auvik gives).
 */
import type { EnvDevice } from '@/lib/api';

export type Tier = 0 | 1 | 2 | 3;

export interface MapNode {
  id: string;
  label: string;
  role: string | null;
  kind: string;
  tier: Tier;
  x: number;
  y: number;
  online: boolean | null;
}

export interface MapEdge {
  from: string;
  to: string;
  /** Port names on each end, as "Gi1/0/1 ↔ LAN", for the hover text. */
  label: string;
  speed: string | null;
}

export interface NetworkMap {
  nodes: MapNode[];
  edges: MapEdge[];
  width: number;
  height: number;
  /** Devices that had links but were left out because the drawing is capped. */
  hidden: number;
}

const EDGE_TIER = new Set(['firewall', 'router', 'utm', 'securityappliance', 'modem', 'telecommunications', 'backhaul']);
const SWITCH_TIER = new Set(['switch', 'l3switch', 'stack', 'chassis', 'hub', 'voipswitch', 'loadbalancer', 'controller', 'packetprocessor']);
const AP_TIER = new Set(['accesspoint', 'thinaccesspoint', 'bridge']);

export const COL_W = 150;
export const ROW_H = 120;
export const PAD = 40;
/** A row longer than this wraps onto another row, so a switch with forty computers does not make the drawing a mile wide. */
export const MAX_PER_ROW = 10;
/** The drawing shows at most this many devices; the lists below it show the rest. */
export const MAX_NODES = 120;

export function tierOf(d: Pick<EnvDevice, 'role' | 'kind'>): Tier {
  const r = (d.role ?? '').toLowerCase();
  if (EDGE_TIER.has(r)) return 0;
  if (SWITCH_TIER.has(r)) return 1;
  if (AP_TIER.has(r)) return 2;
  return d.kind === 'network' ? 1 : 3;
}

const key = (name: string) => name.trim().toLowerCase();

/** The devices that belong in the drawing: every network device that has a link, and every device a link names. Links to a name we do not know are dropped. */
export function buildMap(devices: EnvDevice[]): NetworkMap {
  const byName = new Map<string, EnvDevice>();
  for (const d of devices) if (!byName.has(key(d.hostname))) byName.set(key(d.hostname), d);

  const edges: MapEdge[] = [];
  const seen = new Set<string>();
  const inDrawing = new Set<string>();
  for (const d of devices) {
    for (const l of d.links) {
      const other = byName.get(key(l.name));
      if (!other || other.id === d.id) continue;
      const pair = [d.id, other.id].sort().join('|');
      const dir = `${pair}|${[l.port ?? '', l.remote_port ?? ''].sort().join('|')}`;
      if (seen.has(dir)) continue;
      seen.add(dir);
      inDrawing.add(d.id);
      inDrawing.add(other.id);
      edges.push({ from: d.id, to: other.id, label: `${l.port ?? '?'} ↔ ${l.remote_port ?? '?'}`, speed: l.speed });
    }
  }

  const included = devices.filter((d) => inDrawing.has(d.id));
  const shown = included.slice(0, MAX_NODES);
  const shownIds = new Set(shown.map((d) => d.id));
  const shownEdges = edges.filter((e) => shownIds.has(e.from) && shownIds.has(e.to));

  // Order each tier by where its neighbours sit in the tier above (one pass), so lines cross less.
  const tiers: EnvDevice[][] = [[], [], [], []];
  for (const d of shown) tiers[tierOf(d)].push(d);
  const order = new Map<string, number>();
  tiers.forEach((row, t) => {
    row.sort((a, b) => a.hostname.localeCompare(b.hostname));
    if (t > 0) {
      const bary = (d: EnvDevice) => {
        const xs = shownEdges.flatMap((e) => (e.from === d.id ? [e.to] : e.to === d.id ? [e.from] : [])).map((id) => order.get(id)).filter((n): n is number => n !== undefined);
        return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : Number.MAX_SAFE_INTEGER;
      };
      row.sort((a, b) => bary(a) - bary(b) || a.hostname.localeCompare(b.hostname));
    }
    row.forEach((d, i) => order.set(d.id, i));
  });

  const nodes: MapNode[] = [];
  let y = PAD;
  let widest = 1;
  tiers.forEach((row, t) => {
    if (row.length === 0) return;
    for (let start = 0; start < row.length; start += MAX_PER_ROW) {
      const slice = row.slice(start, start + MAX_PER_ROW);
      widest = Math.max(widest, slice.length);
      slice.forEach((d, i) => nodes.push({ id: d.id, label: d.hostname, role: d.role, kind: d.kind, tier: t as Tier, x: i, y, online: d.online }));
      y += ROW_H;
    }
  });
  // Centre every row on the widest one.
  const rowsByY = new Map<number, MapNode[]>();
  for (const n of nodes) rowsByY.set(n.y, [...(rowsByY.get(n.y) ?? []), n]);
  for (const row of rowsByY.values()) {
    const offset = (widest - row.length) / 2;
    for (const n of row) n.x = PAD + (n.x + offset) * COL_W + COL_W / 2;
  }
  return { nodes, edges: shownEdges, width: PAD * 2 + widest * COL_W, height: y - ROW_H + PAD + 40, hidden: included.length - shown.length };
}
