import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { EnvDevice } from '@/lib/api';
import { CLASS_COLOR, CLASS_PATHS } from './deviceIcons';
import { MIN_SCALE, NetworkMapDrawing, cablePath, statusColor } from './NetworkMapDrawing';
import { CLASS_LABEL, type DeviceClass } from './networkMap';

const dev = (id: string, role: string | null, kind: string, online: boolean | null, to: string[]): EnvDevice => ({
  id, hostname: id, kind, role, online, tools: [], links: to.map((name) => ({ name, port: 'p', remote_port: 'q', speed: null })), missing: [], pushable: [],
});

describe('the network map drawing', () => {
  const devices = [
    dev('fw-1', 'firewall', 'network', true, ['sw-1']),
    dev('sw-1', 'switch', 'network', true, ['fw-1', 'ap-1', 'pc-1']),
    dev('ap-1', 'accesspoint', 'network', false, ['sw-1']),
    dev('pc-1', null, 'computer', null, ['sw-1']),
  ];

  it('gives each card the class of its device, a name for it and a legend entry for each class drawn', () => {
    render(<NetworkMapDrawing devices={devices} clientName="Acme" />);
    const nodes = screen.getAllByTestId('map-node');
    expect(nodes.map((n) => n.getAttribute('data-class')).sort()).toEqual(['firewall', 'switch', 'wap', 'workstation']);
    expect(nodes.find((n) => n.getAttribute('data-class') === 'wap')!.textContent).toContain('Wireless access point');
    expect(screen.getAllByTestId('map-legend').map((l) => l.textContent).sort()).toEqual(['Firewall', 'Switch', 'Wireless access point', 'Workstation']);
    // Each card carries the icon of its class.
    expect(nodes.every((n) => n.querySelector(`[data-icon="${n.getAttribute('data-class')}"]`))).toBe(true);
  });

  it('is never shrunk below a readable share of its natural size: a wide map scrolls sideways instead of squeezing its text', () => {
    const wide = [dev('sw-1', 'switch', 'network', true, []), ...Array.from({ length: 14 }, (_, i) => dev(`pc-${i}`, null, 'computer', true, ['sw-1']))];
    render(<NetworkMapDrawing devices={wide} clientName="Acme" />);
    const svg = screen.getByRole('img', { name: /network devices are connected/ });
    const natural = Number((svg.getAttribute('viewBox') ?? '').split(' ')[2]);
    expect(natural).toBeGreaterThan(1500);
    expect(svg.style.minWidth).toBe(`${Math.round(natural * MIN_SCALE)}px`);
    expect(svg.style.width).toBe('100%');
  });

  it('every class has its own colour and its own icon, so none can be mistaken for another', () => {
    const classes = Object.keys(CLASS_LABEL) as DeviceClass[];
    expect(new Set(classes.map((c) => CLASS_COLOR[c])).size).toBe(classes.length);
    expect(new Set(classes.map((c) => CLASS_PATHS[c].join('|'))).size).toBe(classes.length);
  });

  it('shows online, offline and unknown with different colours, and draws a cable between cards on different rows as a curve', () => {
    expect(new Set([statusColor(true), statusColor(false), statusColor(null)]).size).toBe(3);
    expect(cablePath(10, 20, 50, 20)).toBe('M10 20L50 20');
    expect(cablePath(10, 20, 50, 120)).toBe('M10 20C10 70 50 70 50 120');
  });
});
