/**
 * Line icons for the kinds of device on the network map (firewall, router, switch, controller, wireless access point, server, workstation, laptop, camera, printer, phone, other), each with its own colour.
 * Drawn as plain SVG paths on a 24 by 24 grid so they also survive in the downloaded drawing.
 */
import type { DeviceClass } from './networkMap';

export const CLASS_COLOR: Record<DeviceClass, string> = {
  firewall: '#f97316',
  router: '#f59e0b',
  switch: '#3b82f6',
  controller: '#818cf8',
  wap: '#14b8a6',
  server: '#a78bfa',
  workstation: '#94a3b8',
  laptop: '#38bdf8',
  camera: '#ec4899',
  printer: '#a8a29e',
  phone: '#84cc16',
  other: '#6b7280',
};

export const CLASS_PATHS: Record<DeviceClass, string[]> = {
  firewall: ['M3 5h18v14H3z', 'M3 9.7h18', 'M3 14.3h18', 'M9 5v4.7', 'M15 9.7v4.6', 'M9 14.3V19'],
  router: ['M4 14h16v5H4z', 'M7.5 16.5h.01', 'M11 16.5h.01', 'M8 14V9', 'M16 14V9', 'M8 9L6 6', 'M16 9l2-3'],
  switch: ['M2.5 8h19v8h-19z', 'M5.5 11h2v2h-2z', 'M9.5 11h2v2h-2z', 'M13.5 11h2v2h-2z', 'M17.5 11h2v2h-2z'],
  controller: ['M4 4h16v6H4z', 'M4 14h16v6H4z', 'M8 7h.01', 'M8 17h.01', 'M12 10v4'],
  wap: ['M5 9.5a10 10 0 0 1 14 0', 'M8 12.5a6 6 0 0 1 8 0', 'M10.8 15.4a2 2 0 0 1 2.4 0', 'M12 19h.01'],
  server: ['M4 3.5h16v5H4z', 'M4 10h16v5H4z', 'M4 16.5h16v4H4z', 'M7 6h.01', 'M7 12.5h.01', 'M7 18.5h.01'],
  workstation: ['M3 4h18v12H3z', 'M9 20h6', 'M12 16v4'],
  laptop: ['M5 5h14v10H5z', 'M2 19h20l-2-4H4z'],
  camera: ['M3 8h12v8H3z', 'M15 11l6-3v8l-6-3'],
  printer: ['M7 8V3h10v5', 'M5 8h14v8h-2', 'M5 16h2', 'M7 13h10v8H7z'],
  phone: ['M7 3h10v18H7z', 'M11 18h2'],
  other: ['M12 3l8 4.5v9L12 21l-8-4.5v-9z', 'M12 12l8-4.5', 'M12 12v9', 'M12 12L4 7.5'],
};

/** One icon as an SVG group centred on (x, y), size pixels wide. */
export function DeviceGlyph({ cls, x, y, size = 22, color }: { cls: DeviceClass; x: number; y: number; size?: number; color?: string }) {
  const scale = size / 24;
  return (
    <g transform={`translate(${x - size / 2} ${y - size / 2}) scale(${scale})`} fill="none" stroke={color ?? CLASS_COLOR[cls]} strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round" data-icon={cls}>
      {CLASS_PATHS[cls].map((d, i) => (
        <path key={i} d={d} />
      ))}
    </g>
  );
}
