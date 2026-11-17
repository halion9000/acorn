/**
 * "Does this client not use that tool?" A client whose computers are ALL missing a tool most likely does not use it, so the Devices page offers the "tool this client does not use" tick (on the
 * client's posture page) instead of leaving every one of its computers counted as a gap. Pure over the numbers the Devices summary already holds. Only for one chosen client, and only when there are
 * enough computers to say.
 */

export const MIN_COMPUTERS = 3;

/** The summary field that counts the computers missing each tool. */
const MISSING_FIELD: Record<string, string> = {
  addigy: 'not_in_addigy',
  threatmate: 'not_in_threatmate',
  huntress: 'not_in_huntress',
  screenconnect: 'not_in_screenconnect',
  fieldeffect: 'not_in_fieldeffect',
  ninjaone: 'not_in_ninjaone',
  dnsfilter: 'not_in_dnsfilter',
  autoelevate: 'not_in_autoelevate',
};

export interface UnusedToolHint {
  tool: string;
  computers: number;
}

/** The tools every computer of the client is missing, among the tools that report at all and that the client has not already marked as not used (pure). */
export function unusedToolHints(
  summary: { total: number; kinds?: { computer?: number }; reporting_tools?: string[] } & Record<string, unknown>,
  alreadyExcluded: string[] = [],
  tools: string[] = Object.keys(MISSING_FIELD),
): UnusedToolHint[] {
  const computers = summary.kinds?.computer ?? summary.total;
  if (!Number.isFinite(computers) || computers < MIN_COMPUTERS) return [];
  const reporting = new Set(summary.reporting_tools ?? []);
  const out: UnusedToolHint[] = [];
  for (const tool of tools) {
    const field = MISSING_FIELD[tool];
    const missing = field ? summary[field] : undefined;
    if (!field || typeof missing !== 'number' || alreadyExcluded.includes(tool)) continue;
    // A tool that no device of ANY client reports yet is "not connected", not "not used by this client".
    if (tool !== 'huntress' && tool !== 'addigy' && tool !== 'threatmate' && !reporting.has(tool)) continue;
    if (missing >= computers) out.push({ tool, computers });
  }
  return out;
}
