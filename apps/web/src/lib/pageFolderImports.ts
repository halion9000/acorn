/**
 * A page's folder (src/app/.../<page>/ with its page.tsx) is that page's own: its components, helpers and tests. A file anywhere else that imports from it is leaning on another page's
 * insides, so changing that page breaks something nobody thinks to look at. Shared pieces belong in src/components or src/lib. This finds such imports; pure, so it is tested without a disk.
 *
 * Paths are relative to src/, with forward slashes ("app/(app)/settings/fleet-posture/FleetPosture.tsx").
 */
export interface SourceFile {
  file: string;
  text: string;
}

export interface CrossPageImport {
  /** The file doing the importing. */
  file: string;
  /** What it imports, as a path under src/ without an extension. */
  target: string;
}

const dirname = (p: string): string => (p.includes('/') ? p.slice(0, p.lastIndexOf('/')) : '');

function resolve(fromDir: string, spec: string): string {
  const out = fromDir ? fromDir.split('/') : [];
  for (const part of spec.split('/')) {
    if (part === '.' || part === '') continue;
    if (part === '..') out.pop();
    else out.push(part);
  }
  return out.join('/');
}

/** The folders that hold a page: every folder under app/ with a page.tsx or page.ts in it. */
export function pageFolders(files: readonly string[]): Set<string> {
  return new Set(files.filter((f) => f.startsWith('app/') && /\/page\.tsx?$/.test(f)).map(dirname));
}

/** The page a path belongs to: the nearest folder at or above it that holds a page, or null (a layout folder, a component, a library file). */
export function pageOf(path: string, pages: ReadonlySet<string>): string | null {
  for (let dir = dirname(path); dir !== ''; dir = dirname(dir)) if (pages.has(dir)) return dir;
  return null;
}

/** What a file imports from inside src/: relative paths and the "@/" alias. Packages are left out. */
export function localImports(file: string, text: string): string[] {
  const out: string[] = [];
  for (const m of text.matchAll(/(?:from\s+|import\s*\(\s*|import\s+)(['"])([^'"\n]+)\1/g)) {
    const spec = m[2];
    if (spec.startsWith('@/')) out.push(spec.slice(2));
    else if (spec.startsWith('.')) out.push(resolve(dirname(file), spec));
  }
  return out;
}

/**
 * Every import that reaches into a page's folder from outside it. A file inside a page may import from its own folder and from a page folder above it (a section page and its sub-pages
 * share on purpose); anything else is listed, sorted.
 */
export function crossPageImports(files: readonly SourceFile[]): CrossPageImport[] {
  const pages = pageFolders(files.map((f) => f.file));
  const out: CrossPageImport[] = [];
  for (const { file, text } of files) {
    const mine = pageOf(file, pages);
    for (const target of localImports(file, text)) {
      // The target is a file without its extension, or a folder (its index): either sits in a page folder or is one.
      const theirs = pages.has(target) ? target : pageOf(target, pages);
      if (theirs === null || theirs === mine) continue;
      if (mine !== null && mine.startsWith(`${theirs}/`)) continue;
      out.push({ file, target });
    }
  }
  return out.sort((a, b) => a.file.localeCompare(b.file) || a.target.localeCompare(b.target));
}
