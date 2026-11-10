import { describe, expect, it } from 'vitest';
import { mapFileName, standaloneSvg } from './mapDownload';

const NS = 'http://www.w3.org/2000/svg';

function drawing(): SVGSVGElement {
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', '0 0 640 240');
  svg.setAttribute('style', 'min-width: 640px; width: 100%');
  svg.setAttribute('data-testid', 'the-map');
  const node = document.createElementNS(NS, 'g');
  node.setAttribute('data-testid', 'map-node');
  const label = document.createElementNS(NS, 'text');
  label.textContent = 'fw-1 & <core>';
  node.appendChild(label);
  svg.appendChild(node);
  return svg;
}

describe('mapFileName', () => {
  it('names the client and the day in a form any file system takes', () => {
    const day = new Date('2026-11-10T21:00:00Z');
    expect(mapFileName('Acme Dental, P.C.', day)).toBe('network-map-acme-dental-p-c-2026-11-10.svg');
    expect(mapFileName('  ../..\evil:name?  ', day)).toBe('network-map-evil-name-2026-11-10.svg');
    expect(mapFileName('', day)).toBe('network-map-client-2026-11-10.svg');
    expect(mapFileName('x'.repeat(200), day).length).toBeLessThan(90);
  });
});

describe('standaloneSvg', () => {
  it('is a complete SVG file with its own size and a background, and parses back as SVG', () => {
    const text = standaloneSvg(drawing());
    expect(text.startsWith('<?xml version="1.0" encoding="UTF-8"?>\n<svg')).toBe(true);
    const parsed = new DOMParser().parseFromString(text, 'image/svg+xml').documentElement;
    expect(parsed.nodeName).toBe('svg');
    expect(parsed.namespaceURI).toBe(NS);
    expect(parsed.getAttribute('width')).toBe('640');
    expect(parsed.getAttribute('height')).toBe('240');
    const first = parsed.firstElementChild!;
    expect(first.nodeName).toBe('rect');
    expect(first.getAttribute('width')).toBe('640');
    expect(first.getAttribute('fill')).toBeTruthy();
  });

  it('keeps the labels (safely escaped) and drops what only the page needs', () => {
    const text = standaloneSvg(drawing());
    expect(text).toContain('fw-1 &amp; &lt;core&gt;');
    expect(text).not.toContain('data-testid');
    expect(text).not.toContain('min-width');
  });

  it('leaves the drawing on the page as it was', () => {
    const svg = drawing();
    standaloneSvg(svg);
    expect(svg.getAttribute('data-testid')).toBe('the-map');
    expect(svg.getAttribute('style')).toContain('min-width');
    expect(svg.querySelector('rect')).toBeNull();
  });

  it('a drawing with no usable size still comes out as SVG, without an invented size', () => {
    const svg = document.createElementNS(NS, 'svg');
    const text = standaloneSvg(svg);
    expect(text).toContain('<svg');
    expect(text).not.toContain('width=');
  });
});
