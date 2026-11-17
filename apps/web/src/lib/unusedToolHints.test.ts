import { describe, expect, it } from 'vitest';
import { unusedToolHints } from '@/lib/unusedToolHints';

describe('tools a client probably does not use', () => {
  const base = { total: 10, kinds: { computer: 8 }, reporting_tools: ['ninjaone', 'screenconnect'] };

  it('names the tools every computer is missing, and not the ones some computers have', () => {
    const hints = unusedToolHints({ ...base, not_in_huntress: 8, not_in_threatmate: 3, not_in_ninjaone: 8, not_in_screenconnect: 7 });
    expect(hints).toEqual([{ tool: 'huntress', computers: 8 }, { tool: 'ninjaone', computers: 8 }]);
  });

  it('says nothing for a client with too few computers, for a tool already marked not used, or when a count is missing', () => {
    expect(unusedToolHints({ total: 2, not_in_huntress: 2 })).toEqual([]);
    expect(unusedToolHints({ ...base, not_in_huntress: 8 }, ['huntress'])).toEqual([]);
    expect(unusedToolHints({ ...base })).toEqual([]);
  });

  it('does not call a tool unused when no computer of any client reports it yet', () => {
    expect(unusedToolHints({ total: 5, kinds: { computer: 5 }, reporting_tools: [], not_in_ninjaone: 5, not_in_dnsfilter: 5, not_in_huntress: 5 })).toEqual([{ tool: 'huntress', computers: 5 }]);
  });

  it('counts all devices when the kinds are not given', () => {
    expect(unusedToolHints({ total: 4, not_in_addigy: 4 })).toEqual([{ tool: 'addigy', computers: 4 }]);
  });
});
