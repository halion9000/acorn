import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { calledApiPaths, normalisePath, otherServiceRoutes, servedElsewhere, specPaths, unknownApiCalls } from './apiPaths';

describe('normalising a path', () => {
  it('writes every variable part the same way, and drops the query and a trailing slash', () => {
    expect(normalisePath('/api/v1/cases/${id}/notes')).toBe('/api/v1/cases/{}/notes');
    expect(normalisePath('/api/v1/cases/${encodeURIComponent(c.id)}/notes?limit=${n}')).toBe('/api/v1/cases/{}/notes');
    expect(normalisePath('/api/v1/cases/{case_id}/notes/')).toBe('/api/v1/cases/{}/notes');
    expect(normalisePath('/api/v1/x/${a ? `${b}` : "c"}/y')).toBe('/api/v1/x/{}/y');
  });

  it('treats a variable glued to the end of a part as a query string, not as part of the path', () => {
    expect(normalisePath('/api/v1/devices${query}')).toBe('/api/v1/devices');
    expect(normalisePath('/api/v1/devices/${id}')).toBe('/api/v1/devices/{}');
  });

  it('gives nothing for a pattern that is not one path', () => {
    expect(normalisePath('/api/v1/*')).toBeNull();
    expect(normalisePath('/api/v1/a b')).toBeNull();
  });
});

describe('reading the paths a source calls', () => {
  it('finds quoted and template paths once each, and ignores other text', () => {
    const text = [
      "authFetch('/api/v1/alerts?status=open');",
      'authFetch(`/api/v1/alerts/${id}/notes`);',
      'useJson("/api/v1/alerts");',
      "const other = '/api/v2/alerts'; const page = '/alerts';",
      '// see /api/v1/not-in-quotes',
    ].join('\n');
    expect(calledApiPaths(text)).toEqual(['/api/v1/alerts', '/api/v1/alerts/{}/notes']);
  });
});

describe('the description and the routes to other services', () => {
  const yaml = ['paths:', '  /api/v1/alerts:', '    get:', '  /api/v1/alerts/{alert_id}/notes:', '    post:', 'components:', '  schemas:'].join('\n');
  const config = [
    "{ source: '/api/v1/agents/investigate', destination: `${AGENTS_HOST}/api/v1/agents/investigate` },",
    "{ source: '/api/v1/contextual/:path*', destination: `${AGENTS_HOST}/api/v1/contextual/:path*` },",
    "{ source: '/api/v1/cases/:caseId/investigations/:runId/report.md', destination: `${AGENTS_HOST}/x` },",
    "{ source: '/api/v1/hunt/saved', destination: `${API_HOST}/api/v1/hunt/saved` },",
  ].join('\n');

  it('reads the paths of the description, not its other keys', () => {
    expect([...specPaths(yaml)]).toEqual(['/api/v1/alerts', '/api/v1/alerts/{}/notes']);
  });

  it('keeps only the routes that leave the API', () => {
    expect(otherServiceRoutes(config)).toEqual(['/api/v1/agents/investigate', '/api/v1/contextual/:path*', '/api/v1/cases/:caseId/investigations/:runId/report.md']);
  });

  it('matches a path against those routes part by part', () => {
    const routes = otherServiceRoutes(config);
    expect(servedElsewhere('/api/v1/agents/investigate', routes)).toBe(true);
    expect(servedElsewhere('/api/v1/agents/investigate/more', routes)).toBe(false);
    expect(servedElsewhere('/api/v1/contextual/action/stream', routes)).toBe(true);
    expect(servedElsewhere('/api/v1/contextual', routes)).toBe(true);
    expect(servedElsewhere('/api/v1/cases/{}/investigations/{}/report.md', routes)).toBe(true);
    expect(servedElsewhere('/api/v1/cases/{}/investigations/{}/report.pdf', routes)).toBe(false);
    expect(servedElsewhere('/api/v1/hunt/saved', routes)).toBe(false);
  });

  it('lists a call that is in neither, with the files that make it, and nothing for one that is', () => {
    const files = [
      { file: 'a.tsx', text: "authFetch('/api/v1/alerts'); authFetch(`/api/v1/alerts/${id}/note`);" },
      { file: 'b.tsx', text: "authFetch(`/api/v1/alerts/${x}/note`); authFetch('/api/v1/contextual/actions');" },
    ];
    expect(unknownApiCalls(files, specPaths(yaml), otherServiceRoutes(config))).toEqual([{ path: '/api/v1/alerts/{}/note', files: ['a.tsx', 'b.tsx'] }]);
  });
});

/**
 * Paths the source writes that are in neither place, each with why it is right all the same. The list may only get shorter; a new unknown path fails the build.
 */
const KNOWN: Record<string, string> = {
  '/api/v1/graph_ws/stream': 'a WebSocket route (services/api graph_ws.py): the description lists HTTP paths only',
  '/api/v1/osquery': 'a prefix lib/osquery-api.ts adds its paths to ("/fim/..."), not a path called by itself',
};

function sources(dir: string, root: string, out: { file: string; text: string }[] = []): { file: string; text: string }[] {
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) sources(full, root, out);
    else if (/\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name) && name !== 'apiPaths.ts') out.push({ file: path.relative(root, full).split(path.sep).join('/'), text: readFileSync(full, 'utf8') });
  }
  return out;
}

describe('this application', () => {
  const web = process.cwd();
  const src = path.join(web, 'src');
  const spec = specPaths(readFileSync(path.resolve(web, '..', '..', 'docs', 'openapi.yaml'), 'utf8'));
  const routes = otherServiceRoutes(readFileSync(path.join(web, 'next.config.js'), 'utf8'));
  const unknown = unknownApiCalls(sources(src, src), spec, routes);

  it('calls no API path that does not exist', () => {
    expect(unknown.filter((u) => !(u.path in KNOWN)).map((u) => `${u.path} (${u.files.join(', ')})`)).toEqual([]);
  });

  it('keeps no path on the known list that is no longer called or now exists', () => {
    expect(Object.keys(KNOWN).filter((p) => !unknown.some((u) => u.path === p))).toEqual([]);
  });

  it('read a real description, real routes and real calls (an empty read would pass everything)', () => {
    expect(spec.size).toBeGreaterThan(400);
    expect(routes.length).toBeGreaterThan(3);
    expect(sources(src, src).flatMap((f) => calledApiPaths(f.text)).length).toBeGreaterThan(300);
  });
});
