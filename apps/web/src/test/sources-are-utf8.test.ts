import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/** The production build (Turbopack) refuses a source file that is not valid UTF-8 ("failed to convert rope into string"), and the unit tests do not notice. */
function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) return sources(full);
    return /\.(tsx?|css|json|md)$/.test(name) ? [full] : [];
  });
}

describe('web source files', () => {
  it('are all valid UTF-8, so the production build can read them', () => {
    const decoder = new TextDecoder('utf-8', { fatal: true });
    const bad = sources(path.join(__dirname, '..')).filter((f) => {
      try {
        decoder.decode(readFileSync(f));
        return false;
      } catch {
        return true;
      }
    });
    expect(bad).toEqual([]);
  });
});
