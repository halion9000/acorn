import { describe, expect, it } from 'vitest';
import { boardCsv, csvCell, worstCsv } from './exportCsv';
import type { BoardRow, FleetClient } from './FleetPosture';

describe('csvCell', () => {
  it('quotes a cell with a comma, quote or line break, and doubles its quotes', () => {
    expect(csvCell('a,b')).toBe('"a,b"');
    expect(csvCell('say "hi"')).toBe('"say ""hi"""');
    expect(csvCell('two\nlines')).toBe('"two\nlines"');
    expect(csvCell(null)).toBe('');
    expect(csvCell(7)).toBe('7');
  });

  it('does not let text from a monitored system run as a spreadsheet formula', () => {
    expect(csvCell('=HYPERLINK("http://x")')).toBe('"\'=HYPERLINK(""http://x"")"');
    expect(csvCell('+1')).toBe("'+1");
    expect(csvCell('-2+3')).toBe("'-2+3");
    expect(csvCell('@SUM(A1)')).toBe("'@SUM(A1)");
    expect(csvCell(-3)).toBe('-3');
  });
});

describe('the fleet exports', () => {
  const client = (o: Partial<FleetClient>): FleetClient => ({ client_id: 'c1', client_name: 'Acme', score: 40, met: 1, partly: 1, not_met: 3, accepted: 0, stale_tools: ['ninjaone', 'slide'], ...o });

  it('writes one row per client with its numbers and the tools that stopped updating', () => {
    const csv = worstCsv([client({ target: 80, below_target: true }), client({ client_id: 'c2', client_name: null, score: null, stale_tools: [] })]);
    const [head, a, b] = csv.trimEnd().split('\n');
    expect(head).toBe('Client,Score %,Target %,Below target,Fine,Needs attention,Problems,Accepted,Tools not updating');
    expect(a).toBe('Acme,40,80,yes,1,1,3,0,ninjaone; slide');
    expect(b).toBe('c2,,,,1,1,3,0,');
  });

  it('writes one row per board entry, with the owner, due date and the machines or accounts behind it', () => {
    const row: BoardRow = { client_id: 'c1', client_name: 'Acme', source: 'ninjaone', key: 'ninjaone_patching', status: 'not_met', evidence: '=3 machines, behind', since: '2026-10-01', accepted: true, items: ['srv-01', 'srv-02'], owner: 'Dana R', due_date: '2026-10-30', overdue: true };
    const [head, data] = boardCsv([row]).trimEnd().split('\n');
    expect(head).toBe('Client,Tool,Check,Status,What it saw,Since,Accepted,Owner,Due,Overdue,Items');
    expect(data).toBe('Acme,ninjaone,ninjaone_patching,not_met,"\'=3 machines, behind",2026-10-01,yes,Dana R,2026-10-30,yes,srv-01; srv-02');
  });
});
