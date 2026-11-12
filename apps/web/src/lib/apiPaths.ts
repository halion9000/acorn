/**
 * Which API paths the web application calls, and whether each one exists. A path typed wrong does not fail anything: the page shows an empty list. This compares every path under /api/v1 the
 * source writes with the paths in docs/openapi.yaml, and with the paths next.config sends to another service (those are not in the API's description). Pure, so it is tested without a disk.
 */

/** A path with every variable part written "{}", no query and no trailing slash: "/api/v1/cases/{}/notes". */
export function normalisePath(raw: string): string | null {
  let out = '';
  let depth = 0;
  for (let i = 0; i < raw.length; i++) {
    if (raw.startsWith('${', i)) {
      if (depth === 0) out += '{}';
      depth++;
      i++;
    } else if (depth > 0) {
      if (raw[i] === '{') depth++;
      else if (raw[i] === '}') depth--;
    } else if (raw[i] === '?' || raw[i] === '#') break;
    else out += raw[i];
  }
  // "{id}" as written in a comment or a description is the same variable part.
  out = out.replace(/\{[A-Za-z_][A-Za-z0-9_]*\}/g, '{}');
  // A variable glued to the end of a segment ("/devices${query}") is a query string, not part of the path.
  out = out.replace(/([^/])\{\}$/, '$1').replace(/\/+$/, '');
  if (out === '' || /[\s*<>]/.test(out)) return null;
  return out;
}

/** Every path under /api/v1 that a source text writes in quotes or a template, normalised, in order, each once. */
export function calledApiPaths(text: string): string[] {
  const out = new Set<string>();
  for (const m of text.matchAll(/(['"`])(\/api\/v1\/(?:\$\{(?:[^{}]|\{[^{}]*\})*\}|(?!\1)[^\n\\])*)\1/g)) {
    const path = normalisePath(m[2]);
    if (path !== null) out.add(path);
  }
  return [...out];
}

/** The paths an OpenAPI description (YAML) lists, normalised. */
export function specPaths(yaml: string): Set<string> {
  const out = new Set<string>();
  for (const m of yaml.matchAll(/^ {2}(\/[^\s:]+):\s*$/gm)) {
    const path = normalisePath(m[1]);
    if (path !== null) out.add(path);
  }
  return out;
}

/** The rewrite sources in next.config that go to a service other than the API (their destination does not start with API_HOST), as patterns: ":name" is one part, ":name*" is the rest. */
export function otherServiceRoutes(nextConfig: string): string[] {
  const out: string[] = [];
  for (const m of nextConfig.matchAll(/source:\s*'([^']+)',\s*destination:\s*`\$\{([A-Z_]+)\}/g)) {
    if (m[2] !== 'API_HOST') out.push(m[1]);
  }
  return out;
}

/** Whether a normalised path is covered by one of those patterns. A variable part in the path matches a fixed part of the pattern only when the pattern has a variable there too. */
export function servedElsewhere(path: string, routes: readonly string[]): boolean {
  const parts = path.split('/');
  return routes.some((route) => {
    const want = route.split('/');
    for (let i = 0; i < want.length; i++) {
      if (/^:[A-Za-z_]+\*$/.test(want[i])) return true;
      if (i >= parts.length) return false;
      if (/^:[A-Za-z_]+$/.test(want[i])) continue;
      if (want[i] !== parts[i]) return false;
    }
    return parts.length === want.length;
  });
}

export interface UnknownCall {
  path: string;
  files: string[];
}

/** The paths the source calls that are neither in the description nor sent to another service, each with the files that write it, sorted. */
export function unknownApiCalls(files: readonly { file: string; text: string }[], spec: ReadonlySet<string>, routes: readonly string[]): UnknownCall[] {
  const by = new Map<string, Set<string>>();
  for (const { file, text } of files) {
    for (const path of calledApiPaths(text)) {
      if (spec.has(path) || servedElsewhere(path, routes)) continue;
      (by.get(path) ?? by.set(path, new Set()).get(path)!).add(file);
    }
  }
  return [...by].map(([path, where]) => ({ path, files: [...where].sort() })).sort((a, b) => a.path.localeCompare(b.path));
}
