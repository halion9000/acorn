/**
 * How many data rows a CSV text holds: its records minus the header. A line break inside a quoted field is part of that field (RFC 4180), so it is not counted; a doubled quote inside a quoted
 * field is a literal quote. A trailing line break does not add a row. An empty text, or a header alone, is 0.
 */
export function csvRowCount(body: string): number {
  let records = 0;
  let quoted = false;
  let seenInRecord = false;
  for (let i = 0; i < body.length; i++) {
    const ch = body[i];
    if (ch === '"') {
      quoted = !quoted;
      seenInRecord = true;
    } else if (!quoted && (ch === '\n' || ch === '\r')) {
      if (ch === '\r' && body[i + 1] === '\n') i++;
      if (seenInRecord) records++;
      seenInRecord = false;
    } else {
      seenInRecord = true;
    }
  }
  if (seenInRecord) records++;
  return Math.max(0, records - 1);
}

/** The file name with the number of rows before its extension: "audit-2026-11-11.csv" with 1204 rows is "audit-2026-11-11-1204-rows.csv". A name with no extension gets the count at its end. */
export function withRowCount(filename: string, rows: number): string {
  const n = Math.max(0, Math.floor(rows));
  const tag = `-${n}-row${n === 1 ? '' : 's'}`;
  const dot = filename.lastIndexOf('.');
  return dot > 0 ? `${filename.slice(0, dot)}${tag}${filename.slice(dot)}` : `${filename}${tag}`;
}
