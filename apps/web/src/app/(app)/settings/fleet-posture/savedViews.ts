/**
 * Saved views of the fleet page: a name and where to land (the tab, plus the one setting that tab has: the days of "What changed" or the text of "Search"). Kept in this browser only, so a view
 * is a personal shortcut, not something shared with the team. Reading is forgiving: a damaged entry is dropped, never an error.
 */
export interface SavedView {
  name: string;
  tab: string;
  days?: number;
  q?: string;
}

export const VIEWS_KEY = 'fleet-posture-views';
export const MAX_VIEWS = 20;
const DAYS = [1, 7, 30];

export function parseViews(raw: string | null): SavedView[] {
  if (!raw) return [];
  let list: unknown;
  try {
    list = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(list)) return [];
  const out: SavedView[] = [];
  for (const e of list) {
    const v = e as Partial<SavedView> | null;
    if (!v || typeof v.name !== 'string' || !v.name.trim() || typeof v.tab !== 'string' || !v.tab) continue;
    const view: SavedView = { name: v.name.trim().slice(0, 60), tab: v.tab };
    if (typeof v.days === 'number' && DAYS.includes(v.days)) view.days = v.days;
    if (typeof v.q === 'string' && v.q.trim().length >= 2) view.q = v.q.trim().slice(0, 100);
    if (!out.some((o) => o.name === view.name)) out.push(view);
  }
  return out.slice(0, MAX_VIEWS);
}

/** The views with this one added; a view with the same name is replaced in place. A blank name changes nothing, and nothing is added past the limit. */
export function addView(views: SavedView[], view: SavedView): SavedView[] {
  const clean = parseViews(JSON.stringify([view]))[0];
  if (!clean) return views;
  const at = views.findIndex((v) => v.name === clean.name);
  if (at >= 0) return views.map((v, i) => (i === at ? clean : v));
  return views.length >= MAX_VIEWS ? views : [...views, clean];
}

export const removeView = (views: SavedView[], name: string): SavedView[] => views.filter((v) => v.name !== name);

export function loadViews(): SavedView[] {
  try {
    return parseViews(window.localStorage.getItem(VIEWS_KEY));
  } catch {
    return [];
  }
}

export function storeViews(views: SavedView[]): void {
  try {
    window.localStorage.setItem(VIEWS_KEY, JSON.stringify(views));
  } catch {
    // private windows or blocked storage: the views simply last until the page closes
  }
}
