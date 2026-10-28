/**
 * Which parts of the console a role hides. A role lists whole sections (``section:Automation``) and single pages (their address). This is only about what a person SEES in the sidebar and which pages open;
 * what they may DO is decided by their role's permissions, which the server enforces on every request.
 */

/** Pages nobody can hide from themselves: the home page, and the page where roles are managed (hiding it could lock every administrator out of fixing it). */
export const ALWAYS_VISIBLE: readonly string[] = ['/dashboard', '/settings/rbac'];

export interface CatalogItem {
  label: string;
  href: string;
}

export interface CatalogSection<I extends CatalogItem = CatalogItem> {
  title?: string;
  items: I[];
}

export const sectionKey = (title: string): string => `section:${title}`;

/** True when this page must not be shown: its address is hidden, or the whole section it sits in is. Always-visible pages are never hidden. */
export function isHidden(hidden: ReadonlySet<string>, href: string, sectionTitle?: string): boolean {
  if (ALWAYS_VISIBLE.includes(href)) return false;
  if (hidden.has(href)) return true;
  return !!sectionTitle && hidden.has(sectionKey(sectionTitle));
}

/** The sections with the hidden pages taken out, and a section left with nothing dropped. */
export function visibleSections<I extends CatalogItem, S extends CatalogSection<I>>(sections: S[], hidden: ReadonlySet<string>): S[] {
  if (hidden.size === 0) return sections;
  return sections
    .map((s) => ({ ...s, items: s.items.filter((i) => !isHidden(hidden, i.href, s.title)) }))
    .filter((s) => s.items.length > 0);
}

/**
 * Whether the page the person is on is one their role hides. The longest matching address wins, so hiding /detection does not hide /detection/catalog's own entry the other way round: a path is hidden when the
 * most specific nav entry that covers it is hidden.
 */
/** True when ``pathname`` is ``href`` or a page under it. */
function covers(href: string, pathname: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function pathIsHidden<I extends CatalogItem, S extends CatalogSection<I>>(sections: S[], hidden: ReadonlySet<string>, pathname: string): boolean {
  if (hidden.size === 0) return false;
  // The home page and the roles page are never hidden, whether or not they are sidebar entries of their own.
  if (ALWAYS_VISIBLE.some((a) => covers(a, pathname))) return false;
  let best: { href: string; section?: string } | null = null;
  for (const s of sections) {
    for (const i of s.items) {
      if (covers(i.href, pathname) && (!best || i.href.length > best.href.length)) best = { href: i.href, section: s.title };
    }
  }
  // A page that is not a sidebar entry of its own (the cost dashboard and the roles page sit under Settings) can still be hidden by its address: the longest hidden
  // address that covers it, when that is more specific than the entry it falls under.
  let direct = '';
  for (const h of hidden) if (!h.startsWith('section:') && covers(h, pathname) && h.length > direct.length) direct = h;
  if (direct && (!best || direct.length > best.href.length)) return true;
  return best ? isHidden(hidden, best.href, best.section) : false;
}

/** The entries of a role's hidden list, from whatever the API sent (anything that is not text is ignored). */
/** Pages that moved, by their old address. */
const MOVED_PAGES: Record<string, string> = { '/connectors': '/settings/connectors', '/audit': '/settings/audit', '/costs': '/settings/costs' };

export function toHiddenSet(value: unknown): Set<string> {
  const set = new Set(Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : []);
  // Roles saved before these pages moved into Settings hide them by their old address; keep hiding them at the new one.
  for (const [old, now] of Object.entries(MOVED_PAGES)) if (set.has(old)) set.add(now);
  return set;
}
