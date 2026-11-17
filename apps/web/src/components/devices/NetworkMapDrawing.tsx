'use client';

/**
 * The client's network drawn from Auvik's links: a card for each device with an icon and colour for what it is (firewall, switch, wireless access point, workstation and so on), a status dot, curved cables
 * between them (hover a cable for the ports at each end), and a band behind each row naming it. A card opens the device in Devices.
 */
import { useRef } from 'react';
import type { ClientEnvironment } from '@/lib/api';
import { CLASS_COLOR, DeviceGlyph } from './deviceIcons';
import { downloadText } from '@/lib/download';
import { deviceHref, mapFileName, standaloneSvg } from './mapDownload';
import { CLASS_LABEL, buildMap, type DeviceClass, type Tier } from './networkMap';

const BAND_NAME: Record<Tier, string> = { 0: 'INTERNET EDGE', 1: 'SWITCHING', 2: 'WIRELESS', 3: 'DEVICES' };
const CARD_W = 158;
const CARD_H = 54;

export function statusColor(online: boolean | null): string {
  return online === true ? '#22c55e' : online === false ? '#ef4444' : '#6b7280';
}

/** A cable between two cards as a smooth curve; a cable between two cards on the same row is a straight line. */
export function cablePath(ax: number, ay: number, bx: number, by: number): string {
  if (Math.abs(ay - by) < 1) return `M${ax} ${ay}L${bx} ${by}`;
  const mid = (ay + by) / 2;
  return `M${ax} ${ay}C${ax} ${mid} ${bx} ${mid} ${bx} ${by}`;
}

export function NetworkMapDrawing({ devices, clientName }: { devices: ClientEnvironment['devices']; clientName: string }) {
  const drawing = useRef<SVGSVGElement>(null);
  const map = buildMap(devices);
  if (map.nodes.length === 0) return null;
  const at = new Map(map.nodes.map((n) => [n.id, n]));
  const classes = [...new Set(map.nodes.map((n) => n.cls))] as DeviceClass[];
  const bands = ([0, 1, 2, 3] as Tier[]).flatMap((t) => {
    const ys = map.nodes.filter((n) => n.tier === t).map((n) => n.y);
    return ys.length ? [{ tier: t, top: Math.min(...ys) - 40, bottom: Math.max(...ys) + 40 }] : [];
  });
  return (
    <section aria-label="Network map" className="rounded-xl border border-gray-800 bg-gray-950/50 p-3" data-testid="network-map">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-medium text-gray-200">Network map</h2>
        <div className="flex flex-wrap items-center gap-3 text-[11px] text-gray-400">
          <button
            type="button"
            onClick={() => {
              if (drawing.current) downloadText(mapFileName(clientName, new Date()), standaloneSvg(drawing.current), 'image/svg+xml');
            }}
            className="rounded border border-gray-700 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800"
          >
            Download drawing
          </button>
          {classes.map((c) => (
            <span key={c} className="inline-flex items-center gap-1" data-testid="map-legend">
              <svg width={16} height={16} viewBox="0 0 16 16" aria-hidden="true">
                <DeviceGlyph cls={c} x={8} y={8} size={15} />
              </svg>
              {CLASS_LABEL[c]}
            </span>
          ))}
        </div>
      </div>
      <div className="overflow-x-auto">
        <svg ref={drawing} viewBox={`0 0 ${map.width} ${map.height}`} style={{ minWidth: Math.min(map.width, 900), width: '100%' }} role="img" aria-label="How this client's network devices are connected">
          <defs>
            <linearGradient id="map-card" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#1b2740" />
              <stop offset="100%" stopColor="#0f172a" />
            </linearGradient>
          </defs>
          {bands.map((b) => (
            <g key={b.tier}>
              <rect x={6} y={b.top} width={map.width - 12} height={b.bottom - b.top} rx={10} fill="#ffffff" opacity={b.tier % 2 === 0 ? 0.035 : 0.02} />
              <text x={16} y={b.top + 16} fontSize={9} letterSpacing={1.5} fill="#64748b">
                {BAND_NAME[b.tier]}
              </text>
            </g>
          ))}
          {map.edges.map((e, i) => {
            const a = at.get(e.from);
            const b = at.get(e.to);
            if (!a || !b) return null;
            return (
              <path key={i} d={cablePath(a.x, a.y + (b.y > a.y ? CARD_H / 2 : 0), b.x, b.y - (b.y > a.y ? CARD_H / 2 : 0))} fill="none" stroke="#475569" strokeWidth={1.6} strokeLinecap="round">
                <title>{`${a.label} ↔ ${b.label}: ${e.label}${e.speed ? ` · ${e.speed}` : ''}`}</title>
              </path>
            );
          })}
          {map.nodes.map((n) => {
            const color = CLASS_COLOR[n.cls];
            return (
              <a key={n.id} href={deviceHref(n.label)} aria-label={`Open ${n.label} in Devices`}>
                <g data-testid="map-node" data-class={n.cls} opacity={n.online === false ? 0.55 : 1} style={{ cursor: 'pointer' }}>
                  <rect x={n.x - CARD_W / 2} y={n.y - CARD_H / 2} width={CARD_W} height={CARD_H} rx={10} fill="url(#map-card)" stroke={color} strokeOpacity={0.7} strokeWidth={1.3} />
                  <rect x={n.x - CARD_W / 2} y={n.y - CARD_H / 2 + 8} width={3} height={CARD_H - 16} rx={1.5} fill={color} />
                  <circle cx={n.x - CARD_W / 2 + 28} cy={n.y} r={17} fill={color} fillOpacity={0.14} />
                  <DeviceGlyph cls={n.cls} x={n.x - CARD_W / 2 + 28} y={n.y} size={22} />
                  <text x={n.x - CARD_W / 2 + 52} y={n.y - 3} fontSize={11} fontWeight={600} fill="#f1f5f9">
                    {n.label.length > 17 ? `${n.label.slice(0, 16)}…` : n.label}
                  </text>
                  <text x={n.x - CARD_W / 2 + 52} y={n.y + 11} fontSize={9} fill="#94a3b8">
                    {CLASS_LABEL[n.cls]}
                  </text>
                  <circle cx={n.x + CARD_W / 2 - 10} cy={n.y - CARD_H / 2 + 10} r={4} fill={statusColor(n.online)} />
                  <title>{`${n.label} · ${CLASS_LABEL[n.cls]}${n.role ? ` (${n.role})` : ''}${n.online === false ? ' · offline' : n.online === true ? ' · online' : ''}`}</title>
                </g>
              </a>
            );
          })}
        </svg>
      </div>
      {map.hidden > 0 && <p className="mt-2 text-xs text-gray-500">{map.hidden} more linked devices are in the lists below, not in the drawing.</p>}
    </section>
  );
}
