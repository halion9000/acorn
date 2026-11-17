/**
 * Words typed in the Settings search also look inside the user guide: the sections that contain every word, each with a short piece of text around the first place a word appears, so a person who
 * types "retention" finds the part of the guide that explains it, not only a setting with that name. Pure over the guide text.
 */
import { blockText, parseGuide, slugOf, type GuideSection } from '@/lib/guide-markdown';

export interface GuideHit {
  id: string;
  title: string;
  snippet: string;
}

export const MAX_GUIDE_HITS = 5;
const SNIPPET = 140;

function snippetOf(text: string, words: string[]): string {
  const low = text.toLowerCase();
  const at = Math.min(...words.map((w) => (low.indexOf(w) < 0 ? Infinity : low.indexOf(w))));
  if (!Number.isFinite(at)) return '';
  const start = Math.max(0, at - 40);
  const cut = text.slice(start, start + SNIPPET).replace(/\*\*|`/g, '').replace(/\s+/g, ' ').trim();
  return `${start > 0 ? '…' : ''}${cut}${start + SNIPPET < text.length ? '…' : ''}`;
}

/** The guide sections containing every word of the query (letter case ignored), at most {@link MAX_GUIDE_HITS}, in guide order. Fewer than two letters in total finds nothing (pure). */
export function guideHits(sections: GuideSection[], query: string): GuideHit[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.join('').length < 2) return [];
  const out: GuideHit[] = [];
  for (const s of sections) {
    const body = s.blocks.map(blockText).join(' ');
    const hay = `${s.title} ${body}`.toLowerCase();
    if (!words.every((w) => hay.includes(w))) continue;
    out.push({ id: s.id || slugOf(s.title), title: s.title.replace(/^\d+\.\s*/, ''), snippet: snippetOf(body, words) });
    if (out.length >= MAX_GUIDE_HITS) break;
  }
  return out;
}

let parsed: GuideSection[] | null = null;
/** The guide's sections, parsed once. */
export function guideSections(markdown: string): GuideSection[] {
  parsed ??= parseGuide(markdown).sections;
  return parsed;
}
