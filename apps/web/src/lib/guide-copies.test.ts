import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { USER_GUIDE } from '@/content/user-guide';

/**
 * The user guide is kept in two places: docs/USER_GUIDE.md (for people who read it in the repository) and src/content/user-guide.ts (what the Guide page shows).
 * Nothing used to keep them the same, and they had drifted: the repository copy still listed the Detection Catalog and the Marketplace, which were removed.
 */
const REPO_COPY = path.resolve(process.cwd(), '..', '..', 'docs', 'USER_GUIDE.md');
const normal = (text: string) => text.replace(/\r\n/g, '\n').trimEnd();

function firstDifference(a: string, b: string): string {
  const x = a.split('\n');
  const y = b.split('\n');
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    if (x[i] !== y[i]) return `line ${i + 1}:\n  Guide page: ${JSON.stringify(x[i])}\n  docs/USER_GUIDE.md: ${JSON.stringify(y[i])}`;
  }
  return '';
}

describe('the two copies of the user guide', () => {
  it.skipIf(!existsSync(REPO_COPY))('are the same text', () => {
    const repo = normal(readFileSync(REPO_COPY, 'utf8'));
    const page = normal(USER_GUIDE);
    expect(page === repo ? '' : firstDifference(page, repo), 'the Guide page and docs/USER_GUIDE.md have drifted apart: change both').toBe('');
  });

  it('say nothing about the Detection Catalog or the Marketplace, which were removed', () => {
    expect(USER_GUIDE).not.toMatch(/Detection Catalog|Marketplace/);
  });

  it('describe this month\'s pages: Client Docs, CIPP actions, the run history and closing several alerts at once', () => {
    for (const heading of ['Client Docs (new)', 'CIPP actions (new)', 'Playbooks > Run History (new)', 'Close several at once (new)', 'Every alert for one person (new)']) {
      expect(USER_GUIDE).toContain(heading);
    }
  });
});
