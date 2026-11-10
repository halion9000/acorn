/**
 * The network map as a file: the drawing on the page turned into a stand-alone SVG (its own size, a dark background so the light labels can be read, nothing that only the page needs)
 * and a file name that says which client and which day.
 */
const BACKGROUND = '#0b1220';
const SVG_NS = 'http://www.w3.org/2000/svg';
const NEWLINE = String.fromCharCode(10);

/** "network-map-acme-dental-2026-11-10.svg": lower case, words joined by hyphens, nothing a file system would refuse. */
export function mapFileName(clientName: string, day: Date): string {
  const slug = clientName
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60);
  return `network-map-${slug || 'client'}-${day.toISOString().slice(0, 10)}.svg`;
}

/** The drawing as SVG text that opens by itself in a browser or a document. The element on the page is not changed. */
export function standaloneSvg(svg: SVGSVGElement): string {
  const copy = svg.cloneNode(true) as SVGSVGElement;
  const [, , width, height] = (copy.getAttribute('viewBox') ?? '').split(/\s+/).map(Number);
  if (Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0) {
    copy.setAttribute('width', String(width));
    copy.setAttribute('height', String(height));
    const background = copy.ownerDocument.createElementNS(SVG_NS, 'rect');
    background.setAttribute('width', String(width));
    background.setAttribute('height', String(height));
    background.setAttribute('fill', BACKGROUND);
    copy.insertBefore(background, copy.firstChild);
  }
  copy.removeAttribute('style');
  copy.removeAttribute('class');
  for (const el of [copy, ...Array.from(copy.querySelectorAll('*'))]) el.removeAttribute('data-testid');
  // The serializer writes the SVG namespace itself for an element that is in it (setting it by hand as well would write it twice, which is not valid XML).
  const body = new XMLSerializer().serializeToString(copy);
  const named = /^<svg[^>]*\sxmlns=/.test(body) ? body : body.replace(/^<svg/, `<svg xmlns="${SVG_NS}"`);
  return `<?xml version="1.0" encoding="UTF-8"?>${NEWLINE}${named}`;
}

/** Hands the text to the browser as a download. */
export function downloadText(fileName: string, text: string, type: string): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
