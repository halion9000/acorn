import { describe, expect, it } from 'vitest';

import { csvRowCount, withRowCount } from './auditFileName';

describe('csvRowCount', () => {
  it('counts the records after the header, with or without a trailing line break, in either line ending', () => {
    expect(csvRowCount('when,who\n1,a\n2,b\n')).toBe(2);
    expect(csvRowCount('when,who\n1,a\n2,b')).toBe(2);
    expect(csvRowCount('when,who\r\n1,a\r\n2,b\r\n')).toBe(2);
  });

  it('does not count a line break inside a quoted field, and reads a doubled quote as a quote', () => {
    expect(csvRowCount('when,note\n1,"first line\nsecond line"\n2,"she said ""no""\nand left"\n')).toBe(2);
  });

  it('is 0 for an empty text or a header alone, and skips blank lines', () => {
    expect(csvRowCount('')).toBe(0);
    expect(csvRowCount('when,who\n')).toBe(0);
    expect(csvRowCount('when,who\n\n1,a\n\n')).toBe(1);
  });
});

describe('withRowCount', () => {
  it('puts the count before the extension, in the singular for one', () => {
    expect(withRowCount('audit-2026-11-11.csv', 1204)).toBe('audit-2026-11-11-1204-rows.csv');
    expect(withRowCount('audit.csv', 1)).toBe('audit-1-row.csv');
    expect(withRowCount('audit.csv', 0)).toBe('audit-0-rows.csv');
  });

  it('adds the count at the end of a name with no extension, and only the last dot counts', () => {
    expect(withRowCount('audit', 3)).toBe('audit-3-rows');
    expect(withRowCount('audit.2026.csv', 3)).toBe('audit.2026-3-rows.csv');
  });
});
