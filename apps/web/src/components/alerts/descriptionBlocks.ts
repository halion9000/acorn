/**
 * Turn an alert's description into blocks that read well: prose stays prose, "Label: value" lines become a small table, and a JSON value is shown as formatted code.
 *
 * Tools write descriptions three ways: paragraphs and one "Label: value" per line (Huntress, ThreatMate), or the whole thing run together on one line (NinjaOne). Nothing is invented: a line is a
 * field only when its label is a short capitalised phrase, a run-on line is split only at labels known from those tools, and JSON is formatted only when it parses.
 */

export type DescriptionBlock =
  | { kind: 'text'; text: string }
  | { kind: 'fields'; rows: [string, string][] }
  | { kind: 'code'; text: string };

/** Labels the tools put inside a run-on line, longest first so "Device type" is not read as "Device". */
const RUN_ON_LABELS = ['Condition data', 'Sign-in addresses', 'Logins seen', 'Last contact', 'Last updated', 'Device type', 'Organization', 'Severity', 'Priority', 'Category', 'Raised', 'Source', 'Device', 'Client', 'Asset', 'Person', 'Status'];
const RUN_ON = new RegExp(`(\\s)(${RUN_ON_LABELS.join('|')}):\\s`, 'g');

/** A line with this many known labels is a run-on of fields. */
const RUN_ON_MIN = 3;

function splitRunOn(line: string): string {
  const hits = line.match(RUN_ON);
  if (!hits || hits.length < RUN_ON_MIN) return line;
  return line.replace(RUN_ON, '\n$2: ').replace(/\sDevice is (online|offline)\b/i, '\nStatus: $1');
}

const LABEL = /^([A-Z][A-Za-z0-9\-/()']*(?: [A-Za-z0-9\-/()']+){0,2}):\s+(\S.*)$/;

function asJson(value: string): string | null {
  const v = value.trim();
  if ((!v.startsWith('{') || !v.endsWith('}')) && (!v.startsWith('[') || !v.endsWith(']'))) return null;
  try {
    return JSON.stringify(JSON.parse(v), null, 2);
  } catch {
    return null;
  }
}

export function descriptionBlocks(raw: string | null | undefined): DescriptionBlock[] {
  const text = String(raw ?? '').replace(/\r\n?/g, '\n').trim();
  if (!text) return [];
  const lines = text
    .split('\n')
    .map((l) => splitRunOn(l))
    .join('\n')
    .split('\n');

  const blocks: DescriptionBlock[] = [];
  let rows: [string, string][] = [];
  let prose: string[] = [];
  const flushRows = () => {
    if (rows.length >= 2) blocks.push({ kind: 'fields', rows });
    else if (rows.length === 1) blocks.push({ kind: 'text', text: `${rows[0][0]}: ${rows[0][1]}` });
    rows = [];
  };
  const flushProse = () => {
    const t = prose.join('\n').trim();
    if (t) blocks.push({ kind: 'text', text: t });
    prose = [];
  };
  for (const line of lines) {
    const t = line.trim();
    if (t === '') {
      flushRows();
      flushProse();
      continue;
    }
    const m = LABEL.exec(t);
    if (m) {
      const json = asJson(m[2]);
      if (json !== null) {
        flushRows();
        flushProse();
        blocks.push({ kind: 'text', text: m[1] });
        blocks.push({ kind: 'code', text: json });
        continue;
      }
      flushProse();
      rows.push([m[1], m[2]]);
      continue;
    }
    flushRows();
    prose.push(t);
  }
  flushRows();
  flushProse();
  return blocks;
}
