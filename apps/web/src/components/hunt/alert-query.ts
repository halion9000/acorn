/**
 * Hunt searches the alerts A.C.O.R.N holds (see hunt_alert_search.py: plain words, "quoted phrases", field:value, a leading - for not).
 * A plain-language question is turned into that syntax here, in the browser, so what runs is exactly what the editor shows.
 */

const STOP = new Set(
  ('a an the any all some show me list find get give what which who whom whose is are was were be been do does did have has had there their '
    + 'for at in on with without of to from and or but not no that this these those it its my our your i we you they them any anything something events event '
    + 'alerts alert please can could would should happened happening recent recently latest new today lately over past last severity status '
    // Words that describe how the asker feels about the thing, not what an alert says: no alert title contains "weird".
    + 'weird strange odd funny bad sketchy shady fishy').split(' '),
);
const SEVERITIES = ['critical', 'high', 'medium', 'low', 'info'];
const STATUSES: Record<string, string> = { open: 'open', new: 'new', closed: 'closed', resolved: 'resolved', investigating: 'investigating' };

/** "for any clients", "across all clients", "every client": every client, which is no filter at all (it used to become client:"any clients" and match nothing). */
const ALL_CLIENTS = /\b(?:(?:for|at|in|on|across|from|of)\s+)?(?:any|all|every|each)(?:\s+of)?(?:\s+(?:the|my|our|your))?\s+(?:client|customer|org|organi[sz]ation|tenant)s?\b/gi;
/** Asking about sign-ins from outside the country. The alerts here are titled "Authentication from New Country", "Unexpected Country - Mexico", "Impossible Travel": the one word they share is country. */
const FOREIGN =
  /\b(?:out(?:side)?(?:\s+of)?(?:\s+the)?\s+(?:country|u\.?s\.?a?|states)|abroad|overseas|foreign|non[- ]?u\.?s\.?a?|international|(?:another|other|new|different)\s+countr(?:y|ies))\b/gi;
/** Words for a sign-in that, beside the country idea, would only narrow the search to titles that say "login" (and the country ones do not). */
const SIGN_IN_WORDS = new Set(['login', 'logon', 'signin', 'sign-in', 'authentication', 'auth', 'access', 'attempt']);

function stem(w: string): string {
  return w.length > 4 && w.endsWith('s') && !w.endsWith('ss') && !w.endsWith('us') ? w.slice(0, -1) : w;
}

/** "any suspicious logins at live oak" -> `suspicious login client:"live oak"`. Empty when nothing searchable is left. */
export function questionToAlertSearch(question: string): string {
  let text = (question || '').trim().replace(/[?!.]+$/, '');
  const parts: string[] = [];
  for (const m of text.matchAll(/"([^"]+)"/g)) parts.push(`"${m[1]}"`);
  text = text.replace(/"[^"]*"/g, ' ').replace(ALL_CLIENTS, ' ');
  const foreign = FOREIGN.test(text);
  FOREIGN.lastIndex = 0;
  if (foreign) text = text.replace(FOREIGN, ' country ');
  const org = /\b(?:at|for|in|of)\s+(?:the\s+)?((?:[A-Za-z0-9&'-]+\s*){1,4})$/i.exec(text);
  let client = '';
  if (org) {
    const words = org[1].trim().split(/\s+/);
    if (words.some((w) => !STOP.has(w.toLowerCase()))) {
      client = words.join(' ');
      text = text.slice(0, org.index);
    }
  }
  for (const raw of text.toLowerCase().split(/[^a-z0-9@._:-]+/).filter(Boolean)) {
    if (SEVERITIES.includes(raw)) parts.push(`severity:${raw}`);
    else if (STATUSES[raw]) parts.push(`status:${STATUSES[raw]}`);
    else if (!STOP.has(raw) && !(foreign && SIGN_IN_WORDS.has(stem(raw)))) parts.push(stem(raw));
  }
  if (client) parts.push(`client:"${client}"`);
  return [...new Set(parts)].join(' ');
}
