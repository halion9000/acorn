import { describe, expect, it } from 'vitest';
import { ALWAYS_VISIBLE, isHidden, pathIsHidden, sectionKey, toHiddenSet, visibleSections } from './nav-visibility';

const CATALOG = [
  { items: [{ label: 'Dashboard', href: '/dashboard' }] },
  {
    title: 'Client Security',
    items: [
      { label: 'Client Posture', href: '/settings/client-posture' },
      { label: 'Multi-Factor', href: '/settings/mfa' },
    ],
  },
  {
    title: 'Automation',
    items: [
      { label: 'Playbooks', href: '/playbooks' },
      { label: 'FIM', href: '/fim' },
    ],
  },
  {
    title: 'Platform',
    items: [
      { label: 'Roles', href: '/settings/rbac' },
      { label: 'Settings', href: '/settings' },
    ],
  },
];

const hrefs = (s: typeof CATALOG) => s.flatMap((x) => x.items.map((i) => i.href));

describe('visibleSections', () => {
  it('shows everything when nothing is hidden', () => {
    expect(visibleSections(CATALOG, new Set())).toBe(CATALOG);
  });
  it('hides one page and keeps its neighbours', () => {
    const out = visibleSections(CATALOG, new Set(['/settings/client-posture']));
    expect(hrefs(out)).toContain('/settings/mfa');
    expect(hrefs(out)).not.toContain('/settings/client-posture');
  });
  it('hides a whole section, title and all, and keeps the others', () => {
    const out = visibleSections(CATALOG, new Set([sectionKey('Automation')]));
    expect(out.map((s) => s.title)).toEqual([undefined, 'Client Security', 'Platform']);
  });
  it('drops a section whose every page is hidden', () => {
    const out = visibleSections(CATALOG, new Set(['/playbooks', '/fim']));
    expect(out.map((s) => s.title)).not.toContain('Automation');
  });
  it('never hides the home page or the page where roles are managed', () => {
    const everything = new Set([sectionKey('Platform'), '/dashboard', '/settings/rbac', '/settings']);
    const out = visibleSections(CATALOG, everything);
    expect(hrefs(out)).toEqual(expect.arrayContaining(['/dashboard', '/settings/rbac']));
    expect(hrefs(out)).not.toContain('/settings');
    expect(ALWAYS_VISIBLE).toEqual(['/dashboard', '/settings/rbac']);
  });
});

describe('pathIsHidden', () => {
  it('is true for a hidden page and the pages under it, false for others', () => {
    const hidden = new Set(['/playbooks']);
    expect(pathIsHidden(CATALOG, hidden, '/playbooks')).toBe(true);
    expect(pathIsHidden(CATALOG, hidden, '/playbooks/abc')).toBe(true);
    expect(pathIsHidden(CATALOG, hidden, '/fim')).toBe(false);
    expect(pathIsHidden(CATALOG, hidden, '/playbooksX')).toBe(false);
  });
  it('is true for any page of a hidden section', () => {
    expect(pathIsHidden(CATALOG, new Set([sectionKey('Client Security')]), '/settings/mfa')).toBe(true);
  });
  it('follows the most specific entry: /settings is hidden but /settings/mfa, in a shown section, is not', () => {
    const hidden = new Set(['/settings']);
    expect(pathIsHidden(CATALOG, hidden, '/settings')).toBe(true);
    expect(pathIsHidden(CATALOG, hidden, '/settings/mfa')).toBe(false);
    expect(pathIsHidden(CATALOG, hidden, '/settings/something-else')).toBe(true);
  });
  it('is false for a page that is not in the sidebar, and when nothing is hidden', () => {
    expect(pathIsHidden(CATALOG, new Set(['/fim']), '/login')).toBe(false);
    expect(pathIsHidden(CATALOG, new Set(), '/fim')).toBe(false);
  });
  it('never hides the roles page even when its section is hidden', () => {
    expect(pathIsHidden(CATALOG, new Set([sectionKey('Platform')]), '/settings/rbac')).toBe(false);
  });
});

// The roles page and the cost dashboard are listed under Settings, not as sidebar entries of their own.
const UNDER_SETTINGS = CATALOG.map((s) => ({ ...s, items: s.items.filter((i) => i.href !== '/settings/rbac') }));

describe('pages that are not sidebar entries of their own', () => {
  it('the roles page is never hidden by address, even when Settings and its section are hidden', () => {
    const hidden = new Set(['/settings', '/settings/rbac', sectionKey('Platform')]);
    expect(pathIsHidden(UNDER_SETTINGS, hidden, '/settings/rbac')).toBe(false);
    expect(pathIsHidden(UNDER_SETTINGS, hidden, '/settings/rbac/roles/7')).toBe(false);
    expect(pathIsHidden(UNDER_SETTINGS, hidden, '/settings/connectors')).toBe(true); // the rest of Settings is hidden, as asked
  });
  it('a page under Settings can still be hidden by its own address, and only that page', () => {
    const hidden = new Set(['/settings/costs']);
    expect(pathIsHidden(UNDER_SETTINGS, hidden, '/settings/costs')).toBe(true);
    expect(pathIsHidden(UNDER_SETTINGS, hidden, '/settings')).toBe(false);
    expect(pathIsHidden(UNDER_SETTINGS, hidden, '/settings/connectors')).toBe(false);
  });
});

describe('isHidden and toHiddenSet', () => {
  it('reads a section or a page', () => {
    expect(isHidden(new Set(['/fim']), '/fim', 'Automation')).toBe(true);
    expect(isHidden(new Set([sectionKey('Automation')]), '/fim', 'Automation')).toBe(true);
    expect(isHidden(new Set([sectionKey('Automation')]), '/fim', 'Platform')).toBe(false);
  });
  it('keeps hiding a page that moved into Settings for a role saved with its old address', () => {
    const set = toHiddenSet(['/connectors', '/audit', '/costs']);
    expect(set.has('/settings/connectors')).toBe(true);
    expect(set.has('/settings/audit')).toBe(true);
    expect(set.has('/settings/costs')).toBe(true);
  });
  it('does not tie Settings to the Platform section: each is hidden only when the role says so', () => {
    expect(toHiddenSet(['section:Platform']).has('/settings')).toBe(false);
    expect(toHiddenSet(['/settings']).has('section:Platform')).toBe(false);
  });
  it('ignores anything the API sent that is not text', () => {
    expect([...toHiddenSet(['/a', 3, null, 'section:X'])]).toEqual(['/a', 'section:X']);
    expect(toHiddenSet(undefined).size).toBe(0);
    expect(toHiddenSet('nope').size).toBe(0);
  });
});
