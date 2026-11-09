/**
 * Small CSV helper for "Export CSV" buttons that save the rows already on the screen.
 *
 * One cell per value, quoted when it holds a comma, quote or line break (quotes doubled), CRLF between rows as RFC 4180 says, and a leading byte-order mark so Excel reads accents correctly. A cell that starts with
 * `=`, `+`, `-` or `@` (a spreadsheet would run it as a formula) gets a leading apostrophe, so a hostile alert title cannot turn an export into an attack on whoever opens it.
 */

export type CsvCell = string | number | boolean | null | undefined;

const FORMULA = /^[=+\-@\t\r]/;

export function csvCell(value: CsvCell): string {
  let text = value === null || value === undefined ? '' : String(value);
  if (typeof value === 'string' && FORMULA.test(text)) text = `'${text}`;
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** The whole file text: a header row and one row per record, in the order of the columns. */
export function csvText(headers: string[], rows: CsvCell[][]): string {
  return '﻿' + [headers, ...rows].map((r) => r.map(csvCell).join(',')).join('\r\n') + '\r\n';
}

/** Save the text as a file through the browser. */
export function downloadCsv(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}
