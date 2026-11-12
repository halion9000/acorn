import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { crossPageImports, localImports, pageFolders, pageOf, type SourceFile } from './pageFolderImports';

const page = (dir: string): SourceFile => ({ file: `${dir}/page.tsx`, text: '' });

describe('finding the page a file belongs to', () => {
  const pages = pageFolders(['app/(app)/alerts/page.tsx', 'app/(app)/settings/page.ts', 'app/(app)/settings/roles/page.tsx', 'app/layout.tsx', 'components/alerts/page.tsx']);

  it('a page folder is a folder under app/ with a page file; a layout or a component folder is not', () => {
    expect([...pages].sort()).toEqual(['app/(app)/alerts', 'app/(app)/settings', 'app/(app)/settings/roles']);
  });

  it('a file belongs to the nearest page folder at or above it, or to none', () => {
    expect(pageOf('app/(app)/alerts/parts/Row.tsx', pages)).toBe('app/(app)/alerts');
    expect(pageOf('app/(app)/settings/roles/RoleCard.tsx', pages)).toBe('app/(app)/settings/roles');
    expect(pageOf('app/layout.tsx', pages)).toBeNull();
    expect(pageOf('components/alerts/AlertsView.tsx', pages)).toBeNull();
  });
});

describe('reading what a file imports', () => {
  it('follows relative paths and the @/ alias, in static, side-effect and dynamic imports, and leaves packages out', () => {
    const text = [
      "import React from 'react';",
      "import { a } from './a';",
      'import { b } from "../other/b";',
      "import type { C } from '@/components/c/C';",
      "import './side-effect';",
      "const d = await import('@/app/(app)/d/D');",
      "export { e } from '../../e';",
    ].join('\n');
    expect(localImports('app/(app)/x/File.tsx', text)).toEqual(['app/(app)/x/a', 'app/(app)/other/b', 'components/c/C', 'app/(app)/x/side-effect', 'app/(app)/d/D', 'app/e']);
  });
});

describe('imports that reach into another page’s folder', () => {
  const files: SourceFile[] = [
    page('app/(app)/alerts'),
    page('app/(app)/settings'),
    page('app/(app)/settings/roles'),
    { file: 'app/(app)/alerts/AlertsTable.tsx', text: "import { fmt } from './format';\nimport { Card } from '@/components/ui/card';" },
    { file: 'app/(app)/alerts/Borrow.tsx', text: "import { RoleCard } from '../settings/roles/RoleCard';" },
    { file: 'app/(app)/settings/roles/RoleCard.tsx', text: "import { shared } from '../shared';" },
    { file: 'app/(app)/settings/Section.tsx', text: "import { RoleCard } from './roles/RoleCard';" },
    { file: 'components/reports/Snapshot.tsx', text: "import { NAMES } from '@/app/(app)/alerts/AlertsTable';" },
    { file: 'components/reports/Whole.tsx', text: "import Alerts from '@/app/(app)/alerts';" },
    { file: 'lib/fine.ts', text: "import { x } from '@/lib/other';" },
  ];

  it('lists a page importing from another page, a parent importing from its sub-page, and a component importing from a page (a file or the whole folder)', () => {
    expect(crossPageImports(files)).toEqual([
      { file: 'app/(app)/alerts/Borrow.tsx', target: 'app/(app)/settings/roles/RoleCard' },
      { file: 'app/(app)/settings/Section.tsx', target: 'app/(app)/settings/roles/RoleCard' },
      { file: 'components/reports/Snapshot.tsx', target: 'app/(app)/alerts/AlertsTable' },
      { file: 'components/reports/Whole.tsx', target: 'app/(app)/alerts' },
    ]);
  });

  it('allows a page its own folder, the page folder above it, and anything under components or lib', () => {
    const allowed = crossPageImports(files).map((c) => c.file);
    expect(allowed).not.toContain('app/(app)/alerts/AlertsTable.tsx');
    expect(allowed).not.toContain('app/(app)/settings/roles/RoleCard.tsx');
    expect(allowed).not.toContain('lib/fine.ts');
  });
});

/**
 * The imports that already reached into a page's folder when this check was added (2026-11-12). The list may only get shorter: move the shared piece to src/components or src/lib and
 * delete its line. A new one fails the build.
 */
const KNOWN = [
  'app/(app)/settings/fleet-posture/FleetPosture.tsx -> app/(app)/settings/client-posture/ClientPosture',
  'components/reports/ClientSnapshot.tsx -> app/(app)/reports/client-review/ClientReview',
  'components/reports/ClientSnapshot.tsx -> app/(app)/reports/client-review/review-links',
  'components/vulnerabilities/VulnerabilitiesView.tsx -> app/(app)/settings/client-posture/ToolChecks',
];

function sources(dir: string, root: string, out: SourceFile[] = []): SourceFile[] {
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) sources(full, root, out);
    else if (/\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push({ file: path.relative(root, full).split(path.sep).join('/'), text: readFileSync(full, 'utf8') });
  }
  return out;
}

describe('this application', () => {
  const src = path.resolve(process.cwd(), 'src');
  const found = crossPageImports(sources(src, src)).map((c) => `${c.file} -> ${c.target}`);

  it('has no new import that reaches into another page’s folder', () => {
    expect(found.filter((line) => !KNOWN.includes(line))).toEqual([]);
  });

  it('keeps no line on the known list that is no longer true', () => {
    expect(KNOWN.filter((line) => !found.includes(line))).toEqual([]);
  });

  it('read a real number of files and pages (an empty scan would pass everything)', () => {
    const all = sources(src, src);
    expect(all.length).toBeGreaterThan(300);
    expect(pageFolders(all.map((f) => f.file)).size).toBeGreaterThan(40);
  });
});
