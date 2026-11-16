/**
 * A line by line comparison of two texts, for showing what changed between two versions of a policy. Pure. It finds the longest run of lines the two share (the usual way a diff is made) and marks every
 * other line as added or removed. Lines are compared after trailing spaces are dropped, so a re-saved file with different line endings does not look changed.
 */
export type DiffLine = { kind: 'same' | 'add' | 'del'; text: string };

/** Above this many line pairs the careful comparison is skipped and the whole old text is shown as replaced by the whole new one. */
export const MAX_PAIRS = 4_000_000;

const lines = (t: string): string[] => (t === '' ? [] : t.replace(/\r\n/g, '\n').split('\n').map((l) => l.replace(/\s+$/, '')));

export function lineDiff(oldText: string, newText: string): DiffLine[] {
  const a = lines(oldText);
  const b = lines(newText);
  if (a.length * b.length > MAX_PAIRS) return [...a.map((text) => ({ kind: 'del' as const, text })), ...b.map((text) => ({ kind: 'add' as const, text }))];
  // lcs[i][j]: the length of the longest common run of a[i..] and b[j..]
  const lcs: Uint32Array[] = Array.from({ length: a.length + 1 }, () => new Uint32Array(b.length + 1));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) lcs[i]![j] = a[i] === b[j] ? lcs[i + 1]![j + 1]! + 1 : Math.max(lcs[i + 1]![j]!, lcs[i]![j + 1]!);
  }
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      out.push({ kind: 'same', text: a[i]! });
      i++;
      j++;
    } else if (lcs[i + 1]![j]! >= lcs[i]![j + 1]!) out.push({ kind: 'del', text: a[i++]! });
    else out.push({ kind: 'add', text: b[j++]! });
  }
  while (i < a.length) out.push({ kind: 'del', text: a[i++]! });
  while (j < b.length) out.push({ kind: 'add', text: b[j++]! });
  return out;
}

/** How many lines were added and removed (pure). */
export function diffCounts(d: DiffLine[]): { added: number; removed: number } {
  return { added: d.filter((l) => l.kind === 'add').length, removed: d.filter((l) => l.kind === 'del').length };
}
