# Rewst metric dashboards compared with A.C.O.R.N (2026-11-19)

Compared the Rewst Ticket Summary page (the signed-in site, last 12 months, Dec 2025 to Nov 2026) with A.C.O.R.N's Tickets and satisfaction page, and read how Rewst builds its numbers (the workflow "[RAVEN] Halo - List Ticket Metrics" and its template). Other Rewst pages were not compared number by number yet.

## The numbers

| Month | Rewst created | A.C.O.R.N created | Rewst resolved | A.C.O.R.N resolved |
| --- | --- | --- | --- | --- |
| Jul 2026 | 4,982 | 6,301 | 5,086 | 5,704 |
| Aug 2026 | 5,781 | 7,171 | 5,968 | 7,064 |
| Sep 2026 | 5,827 | 7,193 | 5,826 | 7,110 |
| Oct 2026 | 6,003 | 7,437 | 5,946 | 7,199 |
| Nov 2026 (part) | 3,832 | 5,134 | 3,947 | 5,171 |

A.C.O.R.N counts about 24 percent more created tickets in every full month and 12 to 23 percent more resolved. First response: Rewst shows 7.68 minutes, A.C.O.R.N 1,183 minutes. Rewst holds 37 months (Nov 2023 to Nov 2026); A.C.O.R.N holds 5 (Jul to Nov 2026).

## Why they differ

1. **Different source.** Rewst runs SQL straight against HaloPSA's database (a report call with the query inside). CORE, for A.C.O.R.N, pages through HaloPSA's ticket list (REST) and counts what it gets.
2. **Deleted and merged tickets.** Rewst's query leaves out deleted tickets and tickets merged into another (`FDeleted` and `FMergedIntoFaultid`). The REST list carries no such flag that CORE reads, so merged duplicates count twice. Alert tickets are merged a lot, which fits an excess of about a quarter. NOT VERIFIED against Halo's own merged count.
3. **Created and resolved are the same idea in both** (created by the month of the created date, resolved by the month of the closed date), so the gap is the exclusions above, not the dates.
4. **First response is a different measure.** Rewst averages HaloPSA's own first-response field (`ffirstresponsetime`, counted as 0 when empty) over all tickets, which gives single-digit minutes. A.C.O.R.N takes the clock time from the created date to the first response date, only for tickets that have one, so nights and weekends count and the average is about 20 hours. Neither is wrong; they answer different questions.
5. **How far back.** CORE reads the last 4 whole months and this one because each month is about 75 pages of 100 tickets. Rewst's SQL covers 36 months in one call.
6. **Open tickets.** Rewst counts tickets with no closed date that are not deleted or merged, and gives the average age in days and how many are over 30 days; A.C.O.R.N shows the count by priority.

## What would make them match

Have CORE run the same query Rewst runs (a read-only SELECT through the HaloPSA report call), so created, resolved, open, average first response and 36 months come out the same, with the old paged read as the fallback if HaloPSA refuses. That needs HaloPSA's report permission on CORE's API key, which is not known; see the roadmap item rewst-metrics-number-differences.

## Visuals

The Metrics pages now use the Rewst look: the dark teal gradient, glass cards with rounded corners, big numbers with the label under them, green bars with the value over each, and for tickets a paired column chart of created and resolved by month. The "Showing ... months" line says how many months the data holds. A light version of the same colors is used in the light theme.


## Built 2026-11-19 (Hal: yes, with the paged read as the fallback)

CORE now reads the ticket statistics first through HaloPSA's report call, with the same exclusions as Rewst (deleted and merged tickets left out), the Rewst first-response measure and 36 months (37 calendar months), and falls back to the paged read when HaloPSA refuses the call or the answer does not add up. Every answer is checked against a separate count of the same thing, so rows cut off by the report call are refused and the paged read runs instead; a mismatch is read once more first, because a ticket can arrive while the queries run. The by-type and by-engineer detail covers the newest 12 months. Closed tickets are counted by the closing engineer when HaloPSA accepts that column and by the assigned engineer when it does not. CORE's log line for the ticket metrics says which read was used and why the report call was not.

NOT VERIFIED live: the report call was not run against HaloPSA, so it is not known that CORE's API key may use it. If it may not, nothing changes from before (the paged read runs) and the log line says so. After the next update the numbers should match Rewst's; if they still differ, the log line and this note are the place to look.
