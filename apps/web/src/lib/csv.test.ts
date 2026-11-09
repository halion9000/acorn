import { describe, expect, it } from 'vitest';

import { csvCell, csvText } from './csv';

describe('csvCell', () => {
  it('leaves plain values alone, quotes commas, quotes and line breaks, and doubles quotes', () => {
    expect(csvCell('plain')).toBe('plain');
    expect(csvCell(42)).toBe('42');
    expect(csvCell(false)).toBe('false');
    expect(csvCell(null)).toBe('');
    expect(csvCell(undefined)).toBe('');
    expect(csvCell('a, b')).toBe('"a, b"');
    expect(csvCell('say "hi"')).toBe('"say ""hi"""');
    expect(csvCell('two\nlines')).toBe('"two\nlines"');
  });
  it('stops a spreadsheet running a cell as a formula', () => {
    for (const bad of ['=HYPERLINK("http://evil","x")', '+1+1', '-2+3', '@SUM(A1)', '\tcmd']) {
      const out = csvCell(bad);
      expect(out.replace(/^"/, '').startsWith("'"), bad).toBe(true);
    }
    expect(csvCell(-5)).toBe('-5');
  });
});

describe('csvText', () => {
  it('has a byte-order mark, a header and one CRLF-separated row per record', () => {
    const t = csvText(['Title', 'Severity'], [['Impossible travel', 'high'], ['A, B', 'low']]);
    expect(t).toBe('﻿Title,Severity\r\nImpossible travel,high\r\n"A, B",low\r\n');
  });
  it('is just the header for no rows', () => {
    expect(csvText(['A'], [])).toBe('﻿A\r\n');
  });
});
