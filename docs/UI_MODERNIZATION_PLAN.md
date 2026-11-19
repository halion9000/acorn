# A.C.O.R.N interface modernization plan (2026-11-18)

Written after clicking through the live site (acorn-ext) on a 1440 by 900 window and a phone-width window: Dashboard, SOC Insights, Scorecard, Devices, Alerts, Compliance, Net income, Billing sync, Client summary, Ticket summary and Client posture, plus the 80-link sidebar. This is a plan only; nothing has been changed. Each phase is small enough to ship on its own and every change keeps the existing tests (the pages are covered by 3,700 web tests, so a restyle is checked, not guessed).

## What looks dated today (what I saw)

1. **Everything has the same weight.** Stat tiles, section boxes, filters and tables are all dark boxes with a thin border and small grey text. Nothing says "look here first". Devices opens with eight identical tiles, all showing a dash while loading, then a table.
2. **Numbers are not designed.** Tables right-align numbers but use the body font, no tabular figures, no units in the header, no color for good or bad, no in-cell bars. Net income is a 14-column wall of figures; Ticket summary and Client summary are lists of "name  number" rows with no visual. Percent change is shown as small red or green text only.
3. **Tiny, shouty labels.** Headers and tile labels are 11 to 12 px uppercase grey on near-black. Contrast is low and they are hard to read at a glance (the tile label "CORRELATION INSTA..." is cut off on a phone).
4. **Too many pill-buttons as navigation.** Net income has 12 tab pills in a wrapping row; Settings, Metrics and Compliance repeat the pattern. On a phone the pills wrap into a block that takes the whole first screen.
5. **A long paragraph above every page.** Each page starts with 2 to 4 lines of explanation before the first number. Useful once, noise every day.
6. **Loading looks like emptiness.** Many pages show blank boxes or dashes for several seconds (Devices, Compliance "Loading...", Billing sync). There are no skeleton rows, so a slow read looks like "no data".
7. **Charts are rare and plain.** Apart from SOC Insights sparklines and the Ticket summary bars, numbers are not drawn. Trends (hours, revenue, licenses, tickets) are tables of months.
8. **The sidebar is a list of 80 links** in nine groups, all open, with no search inside it (there is a global search, but the menu itself is long) and the active page is only a faint highlight.
9. **Dark only.** There is a theme toggle in the top bar, but the pages were built for dark; the light mode is untested.
10. **Phone width.** The top bar crams six controls (search, client, time, bell, sign out) into 300 px; tile labels truncate; tables scroll sideways without a hint.

What is already good and should be kept: the dark base color and the green accent, the Inter font, the left sidebar plus global search (Ctrl K), the "Ask Leafy" assistant, and the clear plain-language wording.

## The plan, in order

### Phase 1: a small design system (about 3 days, no page changes yet)

* **Tokens**: one set of colors (background, surface, raised surface, border, text, muted text, accent, good, warn, bad, and a 5-step blue-green scale for heat), type scale (page title 28, section 18, body 14, caption 12; no 11 px, no all-caps except tiny badges), spacing scale (4, 8, 12, 16, 24, 32) and radii. Raise muted text contrast to at least 4.5:1.
* **Tabular figures** (`font-variant-numeric: tabular-nums`) on every number so columns line up, and one `formatNumber`, `formatMoney`, `formatPercent`, `formatDuration` helper used everywhere (today each page formats its own).
* **Components**: `PageHeader` (title, one-line subtitle, actions at the right, an "About this page" link that opens the explanation instead of showing it), `StatCard` (big number, label, delta with an arrow, optional sparkline), `DataTable` (below), `Segmented` control and `SubNav` (replace pill rows), `Skeleton` rows and cards, `EmptyState` (icon, one line, one action), `Badge`, `Tooltip`.
* Keep them in `apps/web/src/components/ui/` with a single page (`/guide/ui` for staff) that shows every component, so the look is reviewed in one place.

### Phase 2: the number-heavy pages (about 1 week)

For each page, the same recipe: a row of 3 to 5 **StatCards** at the top (the figures the page is for, with change since last period and a sparkline), a **chart** for the trend, then the table.

* **Net income** (highest value): 12 tabs become a left sub-navigation grouped as *Profitability* (Revenue to net income, New clients, By industry, Ranking, Client summary), *Books* (P&L, QBO Profitability, Historical revenue, Travel, Hardware COGS, Forecast) and *Workforce* (Hours and utilization), with Inputs under a gear. The main table gets a pinned client column, a sticky header, grouped column headers (Revenue, Costs, Profit), margin shown as a colored bar in the cell with the percent beside it, negative numbers in red with a minus sign, and a "totals" row that stays visible. A chart above: revenue and net income by month; click a bar to set the month.
* **Ticket summary, Client summary, Labor hours, Staff metrics, Scorecard**: big-number cards (tickets created, resolved, first response, open now), a stacked area or bar chart by month, and "by type" or "by engineer" as horizontal bars with the number at the end instead of a name-and-number list. Scorecard: a ranked list with a score bar and the five factors as small stacked segments.
* **Billing sync, Billing, License waste**: a summary strip (lines that differ, licenses unassigned, money at stake if known), then the table with a difference column drawn as a small bar and colored by direction, row hover actions (Approve, Hide) at the right edge, and a filter bar that remembers its choices.
* **Devices, Alerts, Vulnerabilities, Identities**: keep the tables but add saved views as chips, a density switch (comfortable or compact), column chooser, severity as colored dots, last-seen as relative time with the exact time in a tooltip, and a right-hand detail drawer (the current detail opens inline and pushes the list down).
* **SOC Insights and the Dashboard**: SOC Insights is the closest to modern already; apply the new StatCard and fix the long grey paragraph. The Dashboard gets one "what needs me" row first (open critical alerts, failing checks that changed, approvals waiting), then the funnel.

### Phase 3: navigation and shell (about 3 days)

* Sidebar: groups collapse and remember their state, the current group opens by itself, a search box filters the links, a "Pinned" group (pin any page; the app already supports pinning pages in other places), icons at a consistent size, and an icon-only collapsed mode for more table width.
* Top bar: on a phone, keep the menu, the page title and a search icon; move client picker, time and sign out into the avatar menu.
* Breadcrumb and page actions in `PageHeader` so every page has the same top.
* Loading: skeletons on every page that reads slowly (Devices, Compliance, Billing sync, Client posture first), and "last updated 3 minutes ago" with a refresh button instead of a spinner that replaces content.

### Phase 4: polish (about 3 days)

* Light theme that actually works (tokens make it a second set of values, then check every page with the screenshot test below).
* Empty states with a next step, error states that say what to do, and consistent toasts.
* Motion: 150 ms fades for drawers and tabs only; respect reduced motion.
* Accessibility pass: focus rings, table headers with scope, color never the only signal (bar plus number, dot plus word), keyboard shortcuts listed under Ctrl K.
* A visual regression test (screenshots of about 20 key pages at desktop and phone width in both themes) so a later change cannot quietly undo this.

## Page by page (priority in brackets: 1 first)

| Page | What to change | Priority |
|---|---|---|
| Net income (all tabs) | sub-navigation, pinned column, margin bars, month chart, totals row | 1 |
| Ticket summary, Client summary | cards, monthly chart, bars for by-type and by-engineer | 1 |
| Billing sync, License waste | summary strip, difference bars, row actions | 1 |
| Devices | tiles to compact strip, saved-view chips, density, detail drawer, skeletons | 1 |
| Dashboard, SOC Insights | "needs me" row, new StatCard, shorter intro | 2 |
| Scorecard, Staff metrics, Labor hours, Pods | ranked bars, factor segments, heat cells for hours by week | 2 |
| Alerts, Queue, Cases | severity dots, relative times, drawer, density | 2 |
| Client posture, Fleet posture | status matrix as colored cells (met, partly, not met), client rows by tool columns | 2 |
| Compliance (all pages) | framework cards with health rings, controls as a heat grid, calendar view for due dates | 3 |
| Vulnerabilities, Identities, MFA, Secure score | summary strips, bars, saved views | 3 |
| Settings pages | group into sections with a left list, consistent form layout | 3 |
| Roadmap (Upcoming improvements) | board by status, filters for "waiting on me", Approve inline | 3 |

## Charts: what to use

The app already ships small SVG charts. For anything beyond sparklines and bars, use one small library (recommend Recharts or visx with a thin wrapper) so every chart shares colors, tooltips and axes, and a `Chart` wrapper that accepts the same `StatCard` data shapes. No new dependency is added until Phase 2 starts.

## How each change is kept safe

One page per commit, the existing tests updated with the page (they already test text and sorting), a `next build` run before every deploy (a guide-text backtick broke one deploy today), and a before and after screenshot of the page in the commit description.

## Decision needed from Hal

1. Go ahead with Phase 1 (design system, no visible change) and then Phase 2 starting with **Net income**?
2. A light theme: wanted, or dark only?
3. OK to add one chart library (Recharts) in Phase 2?
