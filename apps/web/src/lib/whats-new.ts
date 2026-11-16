/**
 * "What's new": the entries of the user guide that carry a dated "(new, 2026-11-12)" tag, newest first, each with the section it is in. Built from the guide text itself, so a feature that is
 * written up in the guide with its date shows here without anyone keeping a second list. An entry with a tag but no date has no place in a dated list and is left out.
 */
import { slugOf } from '@/lib/guide-markdown';

export interface WhatsNewEntry {
  /** YYYY-MM-DD from the tag. */
  date: string;
  section: string;
  /** The section's address in the guide. */
  sectionId: string;
  /** The entry's own words, without list marker, emphasis marks or the tag. */
  text: string;
}

const DATED = /( ?)\(new((?:,[^),]*)*), (\d{4}-\d{2}-\d{2})\)/g;
const TEXT_MAX = 280;

/** One line of guide text as plain words: no list dash, no bold, italics or code marks, the tag taken out, and a long one cut at a word. */
export function plainEntry(line: string): string {
  const t = line
    .replace(/^\s*[-*]\s+/, '')
    .replace(DATED, '')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/(?<![*\w])\*([^*]+)\*(?![*\w])/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\s+/g, ' ')
    .trim();
  if (t.length <= TEXT_MAX) return t;
  const cut = t.slice(0, TEXT_MAX);
  return `${cut.slice(0, Math.max(cut.lastIndexOf(' '), 1))}…`;
}

/** Every dated-new line of the guide, newest date first (lines with the same date keep their order in the guide). Headings are never entries. */
export function parseWhatsNew(markdown: string): WhatsNewEntry[] {
  const out: WhatsNewEntry[] = [];
  let section = '';
  for (const line of markdown.replace(/\r\n/g, '\n').split('\n')) {
    if (line.startsWith('#')) {
      if (line.startsWith('## ')) section = line.slice(3).trim();
      continue;
    }
    if (!section) continue; // the intro explains the tags; it is not a feature
    for (const m of line.matchAll(DATED)) {
      const date = m[3]!;
      if (!Number.isFinite(Date.parse(`${date}T00:00:00Z`))) continue;
      const text = plainEntry(line);
      if (!text) continue;
      out.push({ date, section: section.replace(/^\d+\.\s*/, '') || 'Guide', sectionId: slugOf(section), text });
      break; // one entry per line, whichever tag comes first
    }
  }
  return out
    .map((e, i) => ({ e, i }))
    .sort((a, b) => (a.e.date === b.e.date ? a.i - b.i : a.e.date < b.e.date ? 1 : -1))
    .map((x) => x.e);
}

/** The entries grouped by date, newest date first (pure). */
export function groupByDate(entries: WhatsNewEntry[]): { date: string; entries: WhatsNewEntry[] }[] {
  const groups: { date: string; entries: WhatsNewEntry[] }[] = [];
  for (const e of entries) {
    const last = groups[groups.length - 1];
    if (last && last.date === e.date) last.entries.push(e);
    else groups.push({ date: e.date, entries: [e] });
  }
  return groups;
}
