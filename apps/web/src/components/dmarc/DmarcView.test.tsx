import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { DmarcView, PolicyProgressPanel, aliasScript, cleanAliasName, dnsRecordsText, policyLabel, mtaStsRow, rateTone, spfLookupRow, tlsRecordsText } from './DmarcView';

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
const status = { configured: true, mailbox: 'lodmarc@goliveoak.com', last_run_at: new Date().toISOString(), last_error: null, stored: 14, rejected: 0, unmatched_reports: 0 };
const row = (over: Record<string, unknown> = {}) => ({ client_id: 'c1', client_name: 'Acme', matched: true, domain: 'acme.com', reports: 4, total: 200, passed: 190, failed: 10, pass_rate: 95, policy: 'none', last_report: '2026-11-02T00:00:00Z', ...over });
let overview: Record<string, unknown>;
let setup: Record<string, unknown>;
let detail: Record<string, unknown>;
let insights: Record<string, unknown> | null;
let countries: Record<string, unknown> | null;
let card: Record<string, unknown> | null;
let lookalikes: Record<string, unknown> | null;
let bimi: Record<string, unknown> | null;
let blocklists: Record<string, unknown> | null;
let reputation: Record<string, unknown> | null;
let tls: Record<string, unknown> | null;

const view = () => (
  <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
    <DmarcView />
  </SWRConfig>
);

beforeEach(() => {
  window.localStorage.clear();
  overview = { days: 30, status, domains: [row()] };
  setup = { mailbox: 'lodmarc@goliveoak.com', mailbox_domain: 'goliveoak.com', lines: [{ client_id: 'c1', client_name: 'Acme Dental', domain: 'acmedental.com', alias: 'acme-dental@goliveoak.com', client_dmarc_rua: 'rua=mailto:acme-dental@goliveoak.com', authorization_record_name: 'acmedental.com._report._dmarc.goliveoak.com', authorization_record_value: 'v=DMARC1' }] };
  detail = { domain: 'acme.com', days: 30, reports: 4, total: 200, passed: 190, failed: 10, policy: 'none', series: [{ day: '2026-11-01', total: 100, passed: 95, failed: 5 }, { day: '2026-11-02', total: 100, passed: 95, failed: 5 }], failing_sources: [{ ip: '9.9.9.9', count: 10, header_from: 'acme.com', envelope_from: 'evil.example', disposition: 'quarantine' }] };
  insights = {
    days: 30, domain: null, emails: 100,
    delivery: { passed: 80, failed_delivered: 8, overridden: 5, quarantined: 4, rejected: 3 },
    rates: { dmarc: 12, dkim: 15.5, spf: 7 },
    series: [{ day: '2026-11-01', total: 50, dmarc_fail: 5, dkim_fail: 8, spf_fail: 3 }, { day: '2026-11-02', total: 50, dmarc_fail: 7, dkim_fail: 7, spf_fail: 4 }],
    senders: [{ name: 'Microsoft 365', identified: true, emails: 90, passed: 90, failed: 0, status: 'passing' }, { name: 'Unknown (9.9.9.9)', identified: false, emails: 10, passed: 0, failed: 10, status: 'failing' }],
    sending_domains: [{ domain: 'acme.com', emails: 100, passed: 88, failed: 12, status: 'partly' }],
    at_risk: [{ name: 'Unknown (9.9.9.9)', identified: false, emails: 10, passed: 0, failed: 10, status: 'failing' }],
  };
  countries = null;
  card = null;
  lookalikes = null;
  bimi = null;
  blocklists = null;
  reputation = null;
  tls = null;
  authFetch.mockReset();
  authFetch.mockImplementation(async (url: string) => {
    if (url.startsWith('/api/v1/dmarc/overview')) return json(200, overview);
    if (url.startsWith('/api/v1/dmarc/countries')) return countries ? json(200, countries) : json(404, {});
    if (url.startsWith('/api/v1/dmarc/insights')) return insights ? json(200, insights) : json(404, {});
    if (url.startsWith('/api/v1/dmarc/setup')) return json(200, setup);
    if (url.startsWith('/api/v1/dmarc/tls')) return tls ? json(200, tls) : json(404, {});
    if (url.includes('/reputation')) return reputation ? json(200, reputation) : json(404, {});
    if (url.includes('/blocklists')) return blocklists ? json(200, blocklists) : json(404, {});
    if (url.includes('/bimi')) return bimi ? json(200, bimi) : json(404, {});
    if (url.includes('/lookalikes')) return lookalikes ? json(200, lookalikes) : json(404, {});
    if (url.includes('/card')) return card ? json(200, card) : json(404, {});
    if (url.startsWith('/api/v1/dmarc/domains/')) return json(200, detail);
    return json(404, {});
  });
});

describe('the helpers', () => {
  it('colours the pass rate: healthy from 98, a look from 90, a problem below, none without mail', () => {
    expect([rateTone(99), rateTone(98), rateTone(97.9), rateTone(90), rateTone(89.9), rateTone(null)]).toEqual(['text-emerald-300', 'text-emerald-300', 'text-amber-300', 'text-amber-300', 'text-red-300', 'text-gray-400']);
  });
  it('says what a policy does in plain words', () => {
    expect([policyLabel('none'), policyLabel('quarantine'), policyLabel('reject')]).toEqual(['Monitor only', 'Quarantine', 'Reject']);
  });
});

describe('DMARC results', () => {
  it('lists each client domain with its messages, pass rate and policy, and says when the mailbox was read', async () => {
    overview.domains = [row({ client_name: 'Birch', domain: 'birch.com', total: 50, passed: 10, failed: 40, pass_rate: 20 }), row()];
    render(view());
    const rows = await screen.findAllByTestId('dmarc-row');
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText('20%')).toHaveClass('text-red-300');
    expect(within(rows[1]).getByText('95%')).toHaveClass('text-amber-300');
    expect(within(rows[1]).getByText('Monitor only')).toBeInTheDocument();
    expect(screen.getByText(/Reading/)).toHaveTextContent('lodmarc@goliveoak.com');
    expect(screen.getByText(/14 reports stored/)).toBeInTheDocument();
  });

  it('opening a domain shows its daily bars and the sources failing DMARC', async () => {
    render(view());
    await userEvent.click(await screen.findByRole('button', { name: 'acme.com' }));
    const panel = await screen.findByRole('region', { name: 'acme.com detail' });
    expect(within(panel).getByRole('img', { name: /Messages per day/ })).toBeInTheDocument();
    expect(within(panel).getByText('9.9.9.9')).toBeInTheDocument();
    expect(within(panel).getByText('evil.example')).toBeInTheDocument();
    expect(within(panel).getByText('quarantine')).toBeInTheDocument();
  });

  it('says plainly when nothing has failed', async () => {
    detail.failing_sources = [];
    render(view());
    await userEvent.click(await screen.findByRole('button', { name: 'acme.com' }));
    expect(await screen.findByText('Nothing failed in this period.')).toBeInTheDocument();
  });

  it('shows the last read error and the reports that could not be matched', async () => {
    overview.status = { ...status, last_error: 'HTTP 403 ErrorAccessDenied', unmatched_reports: 2 };
    overview.domains = [row({ client_name: 'Not matched to a client', matched: false, domain: 'unknown.example' })];
    render(view());
    expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 403 ErrorAccessDenied');
    expect(screen.getByText(/2 reports could not be matched to a client/)).toBeInTheDocument();
  });

  it('with no mailbox set up says so and with no reports explains when they will arrive', async () => {
    overview.status = { ...status, configured: false, mailbox: null };
    overview.domains = [];
    render(view());
    expect(await screen.findByRole('status')).toHaveTextContent(/not set up on the server yet/);
    expect(screen.getByText(/No reports in the last 30 days/)).toBeInTheDocument();
  });

  it('changing the period asks for that period', async () => {
    render(view());
    await screen.findAllByTestId('dmarc-row');
    await userEvent.selectOptions(screen.getByLabelText('Period'), '90 days');
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/api/v1/dmarc/overview?days=90'));
  });

  it('shows the refusal when the person may not read them', async () => {
    authFetch.mockImplementation(async () => json(403, {}));
    render(view());
    expect(await screen.findByRole('alert')).toHaveTextContent('You do not have access to DMARC reports.');
  });
});

describe('DMARC setup', () => {
  it('says for each record whether public DNS shows it yet, and "not checked" when the server did not say', async () => {
    const base = (setup.lines as Record<string, unknown>[])[0]!;
    const line = (over: object) => ({ ...base, ...over });
    setup = { ...setup, lines: [line({ rua_published: true, authorization_published: false })] };
    const a = render(view());
    await userEvent.click(await screen.findByRole('tab', { name: 'Setup' }));
    expect(await screen.findByTestId('rua-status')).toHaveTextContent('_dmarc.acmedental.com: Published');
    expect(screen.getByTestId('authorization-status')).toHaveTextContent('Not seen in DNS yet');
    a.unmount();
    setup = { ...setup, lines: [line({ rua_published: null })] };
    render(view());
    await userEvent.click(await screen.findByRole('tab', { name: 'Setup' }));
    expect(await screen.findByTestId('rua-status')).toHaveTextContent('Not checked');
    expect(screen.getByTestId('authorization-status')).toHaveTextContent('Not checked');
  });

  it('keeps the page no wider than the window: long record lines wrap and the page can shrink so a table scrolls inside its own box', async () => {
    render(view());
    await userEvent.click(await screen.findByRole('tab', { name: 'Setup' }));
    const r = await screen.findByTestId('setup-row');
    for (const text of ['rua=mailto:acme-dental@goliveoak.com', 'acmedental.com._report._dmarc.goliveoak.com', 'v=DMARC1']) expect(within(r).getByText(text)).toHaveClass('break-all');
    expect(within(r).getByText('acmedental.com').closest('td')).toHaveClass('break-all');
    expect(screen.getByRole('heading', { name: 'DMARC reports' }).closest('div.p-6')).toHaveClass('min-w-0', 'max-w-full');
    expect(r.closest('div.overflow-x-auto')).not.toBeNull();
  });

  it('gives each client domain its DMARC record value and the DNS line for your zone, ready to copy', async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: write }, configurable: true });
    render(view());
    await userEvent.click(await screen.findByRole('tab', { name: 'Setup' }));
    const r = await screen.findByTestId('setup-row');
    expect(within(r).getByText('rua=mailto:acme-dental@goliveoak.com')).toBeInTheDocument();
    expect(within(r).getByText('acmedental.com._report._dmarc.goliveoak.com')).toBeInTheDocument();
    await userEvent.click(within(r).getByRole('button', { name: 'Copy the DNS record for acmedental.com' }));
    expect(write).toHaveBeenCalledWith('acmedental.com._report._dmarc.goliveoak.com\tTXT\tv=DMARC1');
    await userEvent.click(within(r).getByRole('button', { name: 'Copy the DMARC record value for acmedental.com' }));
    expect(write).toHaveBeenCalledWith('rua=mailto:acme-dental@goliveoak.com');
  });

  it('says what to do first when the mailbox is not set up, and when no client domains are known', async () => {
    setup = { mailbox: null, mailbox_domain: null, lines: [] };
    const first = render(view());
    await userEvent.click(await screen.findByRole('tab', { name: 'Setup' }));
    expect(await screen.findByText(/Set up the shared mailbox on the server first/)).toBeInTheDocument();
    first.unmount();
    setup = { mailbox: 'lodmarc@goliveoak.com', mailbox_domain: 'goliveoak.com', lines: [] };
    render(view());
    await userEvent.click(await screen.findByRole('tab', { name: 'Setup' }));
    expect(await screen.findByText(/No client domains are known yet/)).toBeInTheDocument();
  });
});

const line = (domain: string, client: string, alias: string) => ({
  client_id: `id-${client}`,
  client_name: client,
  domain,
  alias,
  client_dmarc_rua: `rua=mailto:${alias}`,
  authorization_record_name: `${domain}._report._dmarc.goliveoak.com`,
  authorization_record_value: 'v=DMARC1',
});

describe('the helpers that build the commands', () => {
  it('aliasScript lists each alias once, sorted, 40 to a command', () => {
    const many = Array.from({ length: 85 }, (_, i) => `client-${String(i).padStart(2, '0')}@goliveoak.com`);
    const lines = aliasScript('lodmarc@goliveoak.com', [...many, many[0], many[1]]).split('\n');
    expect(lines).toHaveLength(3);
    expect(lines[0]).toMatch(/^Set-Mailbox -Identity lodmarc@goliveoak\.com -EmailAddresses @\{add="client-00@goliveoak\.com","client-01@goliveoak\.com"/);
    expect(lines.join('').match(/@goliveoak\.com"/g)).toHaveLength(85);
    expect(aliasScript('m@x.com', [])).toBe('');
  });

  it('dnsRecordsText gives one tab-separated line per domain', () => {
    expect(dnsRecordsText([line('a.com', 'A', 'a@goliveoak.com'), line('b.com', 'B', 'b@goliveoak.com')])).toBe(
      'a.com._report._dmarc.goliveoak.com\tTXT\tv=DMARC1\nb.com._report._dmarc.goliveoak.com\tTXT\tv=DMARC1',
    );
  });
});

describe('choosing which domains the setup covers', () => {
  let write: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    write = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: write }, configurable: true });
    setup = {
      mailbox: 'lodmarc@goliveoak.com',
      mailbox_domain: 'goliveoak.com',
      lines: [line('acme.com', 'Acme', 'acme@goliveoak.com'), line('acme.net', 'Acme', 'acme@goliveoak.com'), line('birch.com', 'Birch', 'birch@goliveoak.com')],
    };
  });
  const open = async () => {
    const r = render(view());
    await userEvent.click(await screen.findByRole('tab', { name: 'Setup' }));
    await screen.findAllByTestId('setup-row');
    return r;
  };

  it('every domain starts ticked and the count says how many domains and aliases are covered', async () => {
    await open();
    expect(screen.getAllByRole('checkbox', { name: /^Include (acme|birch)/ }).every((c) => (c as HTMLInputElement).checked)).toBe(true);
    expect(screen.getByTestId('setup-count')).toHaveTextContent('3 of 3 domains selected (2 aliases)'); // two Acme domains share one alias
  });

  it('unticking a domain leaves it out of the commands and dims its row', async () => {
    await open();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Include acme.net' }));
    await userEvent.click(screen.getByRole('checkbox', { name: 'Include birch.com' }));
    expect(screen.getByTestId('setup-count')).toHaveTextContent('1 of 3 domains selected (1 alias)');
    expect(screen.getAllByTestId('setup-row')[1]).toHaveClass('opacity-50');
    await userEvent.click(screen.getByRole('button', { name: 'Copy the PowerShell that creates the selected aliases' }));
    expect(write).toHaveBeenLastCalledWith('Set-Mailbox -Identity lodmarc@goliveoak.com -EmailAddresses @{add="acme@goliveoak.com"}');
    await userEvent.click(screen.getByRole('button', { name: 'Copy the DNS records for the selected domains' }));
    expect(write).toHaveBeenLastCalledWith('acme.com._report._dmarc.goliveoak.com\tTXT\tv=DMARC1');
  });

  it('the header box ticks or unticks everything, and with nothing ticked the copy buttons are off', async () => {
    await open();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Include every domain' }));
    expect(screen.getByTestId('setup-count')).toHaveTextContent('0 of 3 domains selected (0 aliases)');
    expect(screen.getByRole('button', { name: 'Copy the PowerShell that creates the selected aliases' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Copy the DNS records for the selected domains' })).toBeDisabled();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Include every domain' }));
    expect(screen.getByTestId('setup-count')).toHaveTextContent('3 of 3 domains selected');
  });

  it('the header box shows a dash when only some are ticked', async () => {
    await open();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Include birch.com' }));
    expect((screen.getByRole('checkbox', { name: 'Include every domain' }) as HTMLInputElement).indeterminate).toBe(true);
  });

  it('what was left out is remembered when the page is opened again', async () => {
    const first = await open();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Include birch.com' }));
    first.unmount();
    await open();
    expect((screen.getByRole('checkbox', { name: 'Include birch.com' }) as HTMLInputElement).checked).toBe(false);
    expect(screen.getByTestId('setup-count')).toHaveTextContent('2 of 3 domains selected');
  });
});

describe('choosing the alias name', () => {
  beforeEach(() => {
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn().mockResolvedValue(undefined) }, configurable: true });
    setup = {
      mailbox: 'lodmarc@goliveoak.com',
      mailbox_domain: 'goliveoak.com',
      lines: [line('lonestar.com', 'Lonestar Landscape', 'lonestar-landscape-dfw-llc.dmarc@goliveoak.com'), line('lonestar.net', 'Lonestar Landscape', 'lonestar-landscape-dfw-llc.dmarc@goliveoak.com')],
    };
  });
  const open = async () => {
    const r = render(view());
    await userEvent.click(await screen.findByRole('tab', { name: 'Setup' }));
    await screen.findAllByTestId('setup-row');
    return r;
  };

  it('cleanAliasName keeps a safe name: lower case, allowed characters, starting with a letter or digit, at most 64', () => {
    expect(cleanAliasName('LoneStar.DMARC')).toBe('lonestar.dmarc');
    expect(cleanAliasName(' lone star@x!')).toBe('lonestarx');
    expect(cleanAliasName('..-a_b')).toBe('a_b');
    expect(cleanAliasName('x'.repeat(80))).toHaveLength(64);
    expect(cleanAliasName('@@@')).toBe('');
  });

  it('the alias name can be changed for a client: the record value, the PowerShell and the count follow, for all of its domains', async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: write }, configurable: true });
    await open();
    const [first, second] = screen.getAllByLabelText('Alias for Lonestar Landscape');
    expect(first).toHaveValue('lonestar-landscape-dfw-llc.dmarc');
    await userEvent.clear(first);
    await userEvent.type(first, 'Lonestar.DMARC');
    expect(first).toHaveValue('lonestar.dmarc');
    expect(second).toHaveValue('lonestar.dmarc'); // one alias per client
    expect(screen.getAllByText('rua=mailto:lonestar.dmarc@goliveoak.com')).toHaveLength(2);
    expect(screen.getByTestId('setup-count')).toHaveTextContent('2 of 2 domains selected (1 alias)');
    await userEvent.click(screen.getByRole('button', { name: 'Copy the PowerShell that creates the selected aliases' }));
    expect(write).toHaveBeenLastCalledWith('Set-Mailbox -Identity lodmarc@goliveoak.com -EmailAddresses @{add="lonestar.dmarc@goliveoak.com"}');
  });

  it('the chosen name is remembered, and an empty box means the suggested name', async () => {
    const first = await open();
    await userEvent.clear(screen.getAllByLabelText('Alias for Lonestar Landscape')[0]);
    await userEvent.type(screen.getAllByLabelText('Alias for Lonestar Landscape')[0], 'lonestar.dmarc');
    first.unmount();
    await open();
    expect(screen.getAllByLabelText('Alias for Lonestar Landscape')[0]).toHaveValue('lonestar.dmarc');
    await userEvent.clear(screen.getAllByLabelText('Alias for Lonestar Landscape')[0]);
    expect(screen.getAllByLabelText('Alias for Lonestar Landscape')[0]).toHaveValue(''); // empty while you type a new one...
    expect(screen.getAllByText('rua=mailto:lonestar-landscape-dfw-llc.dmarc@goliveoak.com')).toHaveLength(2); // ...and the suggested name is used if it stays empty
  });
});

describe('domains with no mail records', () => {
  beforeEach(() => {
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn().mockResolvedValue(undefined) }, configurable: true });
    setup = {
      mailbox: 'lodmarc@goliveoak.com',
      mailbox_domain: 'goliveoak.com',
      lines: [{ ...line('acme.com', 'Acme', 'acme.dmarc@goliveoak.com'), has_mx: true }, { ...line('parked.example', 'Acme', 'acme.dmarc@goliveoak.com'), has_mx: false }, { ...line('old.example', 'Birch', 'birch.dmarc@goliveoak.com'), has_mx: false }],
    };
  });
  const open = async () => {
    const r = render(view());
    await userEvent.click(await screen.findByRole('tab', { name: 'Setup' }));
    await screen.findAllByTestId('setup-row');
    return r;
  };

  it('are hidden by default, left out of the count, and the page says how many and why', async () => {
    await open();
    expect(screen.getAllByTestId('setup-row')).toHaveLength(1);
    expect(screen.queryByText('parked.example')).not.toBeInTheDocument();
    expect(screen.getByTestId('setup-count')).toHaveTextContent('1 of 3 domains selected (1 alias)');
    expect(screen.getByTestId('setup-nomail')).toHaveTextContent('2 domains are hidden: no mail records (MX), so nothing to report.');
  });

  it('can be shown, marked "no mail" and unticked; ticking one covers it', async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: write }, configurable: true });
    await open();
    await userEvent.click(screen.getByRole('button', { name: 'Show them' }));
    expect(screen.getAllByTestId('setup-row')).toHaveLength(3);
    expect(screen.getAllByText('no mail')).toHaveLength(2);
    expect((screen.getByRole('checkbox', { name: 'Include parked.example' }) as HTMLInputElement).checked).toBe(false);
    await userEvent.click(screen.getByRole('checkbox', { name: 'Include parked.example' }));
    expect(screen.getByTestId('setup-count')).toHaveTextContent('2 of 3 domains selected');
    await userEvent.click(screen.getByRole('button', { name: 'Copy the DNS records for the selected domains' }));
    expect(write).toHaveBeenLastCalledWith('acme.com._report._dmarc.goliveoak.com\tTXT\tv=DMARC1\nparked.example._report._dmarc.goliveoak.com\tTXT\tv=DMARC1');
    await userEvent.click(screen.getByRole('button', { name: 'Hide the domains without mail' }));
    expect(screen.getAllByTestId('setup-row')).toHaveLength(1);
  });

  it('the header box only touches the rows on screen', async () => {
    await open();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Include every domain' })); // the one visible row off
    expect(screen.getByTestId('setup-count')).toHaveTextContent('0 of 3 domains selected');
    await userEvent.click(screen.getByRole('checkbox', { name: 'Include every domain' })); // back on; the hidden ones stay as they were (off)
    expect(screen.getByTestId('setup-count')).toHaveTextContent('1 of 3 domains selected');
  });

  it('a server that does not say (an older one) is treated as having mail: nothing is hidden', async () => {
    setup = { mailbox: 'lodmarc@goliveoak.com', mailbox_domain: 'goliveoak.com', lines: [line('acme.com', 'Acme', 'acme.dmarc@goliveoak.com')] };
    await open();
    expect(screen.getAllByTestId('setup-row')).toHaveLength(1);
    expect(screen.queryByTestId('setup-nomail')).not.toBeInTheDocument();
  });
});

describe('DMARC mail overview', () => {
  it('shows the five delivery counts, the failure rates, the top senders and the top sending domains', async () => {
    render(view());
    expect(await screen.findByTestId('delivery-passed')).toHaveTextContent('80');
    expect(screen.getByTestId('delivery-failed_delivered')).toHaveTextContent('8');
    expect(screen.getByTestId('delivery-overridden')).toHaveTextContent('5');
    expect(screen.getByTestId('delivery-quarantined')).toHaveTextContent('4');
    expect(screen.getByTestId('delivery-rejected')).toHaveTextContent('3');
    expect(screen.getByText(/DMARC 12%/)).toBeInTheDocument();
    expect(screen.getByText(/DKIM 15.5%/)).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Failure rate per day' })).toBeInTheDocument();
    const senders = screen.getAllByTestId('sender-row');
    expect(within(senders[0]).getByText('Microsoft 365')).toBeInTheDocument();
    expect(within(senders[1]).getByText('failing')).toHaveClass('text-red-300');
    expect(within(screen.getByTestId('sending-domain-row')).getByText('partly')).toBeInTheDocument();
  });

  it('shows nothing extra when the server has no insights, and the table still appears', async () => {
    insights = null;
    render(view());
    expect(await screen.findAllByTestId('dmarc-row')).toHaveLength(1);
    expect(screen.queryByTestId('delivery-passed')).toBeNull();
  });
});

describe('DMARC countries', () => {
  it('lists the countries busiest first with their failures, and says how much could not be placed', async () => {
    countries = { days: 30, emails: 100, countries: [{ code: 'US', emails: 70, passed: 60, failed: 10 }, { code: 'AU', emails: 20, passed: 20, failed: 0 }], unknown: 4, not_looked_up: 6 };
    render(view());
    const rows = await screen.findAllByTestId('country-row');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('United States');
    expect(rows[0]).toHaveTextContent('10 failed');
    expect(rows[1]).toHaveTextContent('all pass');
    expect(screen.getByTestId('country-unplaced')).toHaveTextContent('10 messages could not be placed');
  });

  it('is left out when nothing could be placed or the server has no such route', async () => {
    countries = null;
    render(view());
    await screen.findByTestId('delivery-passed');
    expect(screen.queryByTestId('country-row')).toBeNull();
  });
});

describe('DMARC domain report card', () => {
  it('shows what DNS says for the domain and the next steps when a domain is opened', async () => {
    card = {
      domain: 'acme.com', days: 30, total: 200, pass_rate: 95, policy: 'none',
      posture: {
        domain: 'acme.com', status: 'needs_work', mx: ['acme-com.mail.protection.outlook.com'], mail_provider: 'Microsoft 365',
        spf: { status: 'good', summary: 'SPF is set and ends in -all', record: 'v=spf1 -all', issues: [] },
        dmarc: { status: 'needs_work', summary: "policy is 'none'", record: 'v=DMARC1; p=none', issues: [] },
        dkim: { status: 'good', summary: 'DKIM found', record: null, issues: [] },
      },
      advice: ['Only 95% of mail passes. Find the failing senders first.'],
    };
    render(view());
    await userEvent.click(await screen.findByRole('button', { name: 'acme.com' }));
    const shown = await screen.findByTestId('report-card');
    expect(within(shown).getByTestId('card-mail-records')).toHaveTextContent('Microsoft 365');
    expect(within(shown).getByTestId('card-spf')).toHaveClass('text-emerald-300');
    expect(within(shown).getByTestId('card-dmarc')).toHaveClass('text-amber-300');
    expect(within(shown).getByText(/Find the failing senders/)).toBeInTheDocument();
  });

  it('is left out, and the rest of the detail still shows, when the card is unavailable', async () => {
    card = null;
    render(view());
    await userEvent.click(await screen.findByRole('button', { name: 'acme.com' }));
    await screen.findByText(/Sources failing DMARC/);
    expect(screen.queryByTestId('report-card')).toBeNull();
  });

  it('says plainly when the domain has no mail records', async () => {
    card = {
      domain: 'acme.com', days: 30, total: 200, pass_rate: 100, policy: 'none',
      posture: { domain: 'acme.com', status: 'needs_work', mx: [], mail_provider: null, spf: { status: 'good', summary: 'ok', record: null, issues: [] }, dmarc: { status: 'good', summary: 'ok', record: null, issues: [] }, dkim: { status: 'good', summary: 'ok', record: null, issues: [] } },
      advice: [],
    };
    render(view());
    await userEvent.click(await screen.findByRole('button', { name: 'acme.com' }));
    const mail = await screen.findByTestId('card-mail-records');
    expect(mail).toHaveTextContent('cannot receive mail');
    expect(mail).toHaveClass('text-amber-300');
  });
});

describe('DMARC senders at risk', () => {
  it('lists the senders failing DMARC with how much of their mail fails', async () => {
    render(view());
    const row = await screen.findByTestId('at-risk-row');
    expect(row).toHaveTextContent('Unknown (9.9.9.9)');
    expect(row).toHaveTextContent('10 of 10 failing');
  });

  it('is left out when no sender is failing, or the server does not send it', async () => {
    (insights as { at_risk?: unknown[] }).at_risk = [];
    render(view());
    await screen.findByTestId('delivery-passed');
    expect(screen.queryByTestId('at-risk')).toBeNull();
  });
});

describe('DMARC look-alike domains', () => {
  it('asks only when the button is pressed, then lists what exists with the mail-capable ones marked', async () => {
    lookalikes = { domain: 'acme.com', checked: 27, found: [{ domain: 'acme.co', kind: 'other-ending', has_mail: true }, { domain: 'acm.com', kind: 'omission', has_mail: false }] };
    render(view());
    await userEvent.click(await screen.findByRole('button', { name: 'acme.com' }));
    await screen.findByTestId('lookalikes');
    expect(authFetch.mock.calls.some(([u]) => String(u).includes('/lookalikes'))).toBe(false);
    await userEvent.click(screen.getByRole('button', { name: 'Check for look-alikes' }));
    const rows = await screen.findAllByTestId('lookalike-row');
    expect(rows[0]).toHaveTextContent('acme.co');
    expect(rows[0]).toHaveTextContent('can send mail');
    expect(rows[1]).toHaveTextContent('letter dropped');
    expect(rows[1]).toHaveTextContent('registered');
  });

  it('says none were found, with what that does not cover', async () => {
    lookalikes = { domain: 'acme.com', checked: 27, found: [] };
    render(view());
    await userEvent.click(await screen.findByRole('button', { name: 'acme.com' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Check for look-alikes' }));
    expect(await screen.findByText(/None found among 27 names tried/)).toBeInTheDocument();
  });

  it('shows the reason when the check fails', async () => {
    lookalikes = null;
    render(view());
    await userEvent.click(await screen.findByRole('button', { name: 'acme.com' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Check for look-alikes' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The server answered 404');
  });
});

describe('DMARC brand logo (BIMI) check', () => {
  it('asks only on request, then shows the record, DMARC readiness, certificate life and problems', async () => {
    bimi = {
      domain: 'acme.com', published: true, logo_url: 'https://acme.com/l.svg', certificate_url: 'https://acme.com/v.pem', dmarc_ready: true,
      certificate: { organization: 'Acme Dental LLC', not_after: '2026-11-15T00:00:00Z', days_left: 12, valid: true, is_vmc: true },
      problems: ['The certificate expires in 12 days (2026-11-15). When it lapses the logo disappears without warning.'],
    };
    render(view());
    await userEvent.click(await screen.findByRole('button', { name: 'acme.com' }));
    await screen.findByTestId('bimi');
    expect(authFetch.mock.calls.some(([u]) => String(u).includes('/bimi'))).toBe(false);
    await userEvent.click(screen.getByRole('button', { name: 'Check logo setup' }));
    expect(await screen.findByTestId('bimi-published')).toHaveTextContent('A BIMI record is published');
    expect(screen.getByTestId('bimi-dmarc')).toHaveClass('text-emerald-300');
    expect(screen.getByTestId('bimi-cert')).toHaveTextContent('12 days left');
    expect(screen.getByTestId('bimi-cert')).toHaveClass('text-red-300');
    expect(screen.getByText(/disappears without warning/)).toBeInTheDocument();
  });

  it('says plainly when nothing is published and DMARC is not ready', async () => {
    bimi = { domain: 'acme.com', published: false, logo_url: null, certificate_url: null, dmarc_ready: false, certificate: null, problems: ["DMARC policy is 'none'; BIMI needs quarantine or reject."] };
    render(view());
    await userEvent.click(await screen.findByRole('button', { name: 'acme.com' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Check logo setup' }));
    expect(await screen.findByTestId('bimi-published')).toHaveTextContent('No BIMI record published');
    expect(screen.getByTestId('bimi-dmarc')).toHaveClass('text-amber-300');
    expect(screen.queryByTestId('bimi-cert')).toBeNull();
  });
});

describe('DMARC blocklists', () => {
  it('asks only on request, lists what is listed or not checked, and never calls a refusal clean', async () => {
    blocklists = {
      domain: 'acme.com', listed: 1, not_checked: 2,
      domain_results: [{ list_name: 'Spamhaus DBL', status: 'clear', detail: '' }],
      addresses: [{ ip: '8.8.8.8', emails: 40, results: [{ list_name: 'Spamhaus ZEN', status: 'listed', detail: '127.0.0.2' }, { list_name: 'SpamCop', status: 'clear', detail: '' }, { list_name: 'UCEPROTECT level 1', status: 'no_answer', detail: 'x' }] }, { ip: '1.1.1.1', emails: 20, results: [{ list_name: 'Spamhaus ZEN', status: 'refused', detail: 'x' }] }],
    };
    render(view());
    await userEvent.click(await screen.findByRole('button', { name: 'acme.com' }));
    await screen.findByTestId('blocklists');
    expect(authFetch.mock.calls.some(([u]) => String(u).includes('/blocklists'))).toBe(false);
    await userEvent.click(screen.getByRole('button', { name: 'Check blocklists' }));
    const summary = await screen.findByTestId('blocklist-summary');
    expect(summary).toHaveTextContent('1 listing found.');
    expect(summary).toHaveTextContent('2 checks could not be completed');
    expect(summary).toHaveTextContent('not a clean result');
    const rows = screen.getAllByTestId('blocklist-row');
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent('LISTED');
    expect(rows.map((r) => r.textContent).join('|')).toContain('list refused to answer');
    expect(rows.map((r) => r.textContent).join('|')).not.toContain('SpamCop');
  });

  it('says no listings when everything answered clear', async () => {
    blocklists = { domain: 'acme.com', listed: 0, not_checked: 0, domain_results: [{ list_name: 'Spamhaus DBL', status: 'clear', detail: '' }], addresses: [] };
    render(view());
    await userEvent.click(await screen.findByRole('button', { name: 'acme.com' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Check blocklists' }));
    const summary = await screen.findByTestId('blocklist-summary');
    expect(summary).toHaveTextContent('No listings found.');
    expect(summary).toHaveClass('text-emerald-300');
    expect(screen.queryByTestId('blocklist-row')).toBeNull();
  });
});

describe('DMARC domain reputation', () => {
  it('asks only on request and shows each fact in its own colour, unknown included', async () => {
    reputation = {
      domain: 'acme.com',
      facts: [
        { label: 'Registered', text: '2010-01-01 (16 years ago).', tone: 'good' },
        { label: 'Registration ends', text: 'Expires in 12 days (2026-11-15).', tone: 'warn' },
        { label: 'Its own mail', text: '80.0% of 1,000 messages pass DMARC; 200 failed.', tone: 'bad' },
        { label: 'DMARC policy', text: 'The registration record could not be fetched: x', tone: 'unknown' },
      ],
    };
    render(view());
    await userEvent.click(await screen.findByRole('button', { name: 'acme.com' }));
    await screen.findByTestId('reputation');
    expect(authFetch.mock.calls.some(([u]) => String(u).includes('/reputation'))).toBe(false);
    await userEvent.click(screen.getByRole('button', { name: 'Check reputation' }));
    expect(await screen.findByTestId('reputation-registered')).toHaveClass('text-emerald-300');
    expect(screen.getByTestId('reputation-registration-ends')).toHaveClass('text-amber-300');
    expect(screen.getByTestId('reputation-its-own-mail')).toHaveClass('text-red-300');
    expect(screen.getByTestId('reputation-dmarc-policy')).toHaveClass('text-gray-400');
  });

  it('shows the reason when the check fails', async () => {
    reputation = null;
    render(view());
    await userEvent.click(await screen.findByRole('button', { name: 'acme.com' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Check reputation' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The server answered 404');
  });
});

describe('DMARC TLS reports', () => {
  it('shows each domain with how much encrypted delivery worked and why the rest failed', async () => {
    tls = { days: 30, domains: [{ domain: 'acme.com', client_id: 'c1', matched: true, reports: 2, success: 190, failure: 10, success_rate: 95, failures: [{ type: 'certificate-expired', count: 6 }, { type: 'starttls-not-supported', count: 4 }], last_report: '2026-11-02T00:00:00Z' }] };
    render(view());
    const row = await screen.findByTestId('tls-row');
    expect(row).toHaveTextContent('acme.com');
    expect(row).toHaveTextContent('200');
    expect(within(row).getByText('95%')).toHaveClass('text-amber-300');
    expect(row).toHaveTextContent('certificate-expired (6), starttls-not-supported (4)');
  });

  it('is left out when no TLS report has arrived', async () => {
    tls = { days: 30, domains: [] };
    render(view());
    await screen.findByTestId('delivery-passed');
    expect(screen.queryByTestId('tls-row')).toBeNull();
  });

  it('writes the TLS-reporting record for each ticked domain at the alias chosen for it', () => {
    const line = { client_id: 'c1', client_name: 'Acme', domain: 'acme.com', alias: 'acme.dmarc@goliveoak.com', client_dmarc_rua: '', authorization_record_name: '', authorization_record_value: '' };
    expect(tlsRecordsText([line], () => 'lonestar.dmarc@goliveoak.com')).toBe('_smtp._tls.acme.com\tTXT\tv=TLSRPTv1; rua=mailto:lonestar.dmarc@goliveoak.com');
  });

  it('has a Setup button that copies the TLS records for the ticked domains', async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: write }, configurable: true });
    render(view());
    await userEvent.click(await screen.findByRole('tab', { name: 'Setup' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Copy the TLS report records for the selected domains' }));
    expect(write).toHaveBeenCalledWith('_smtp._tls.acmedental.com\tTXT\tv=TLSRPTv1; rua=mailto:acme-dental@goliveoak.com');
  });
});

describe('the SPF lookup row', () => {
  it('shows nothing without a count, a green count under 8, amber from 8, and red above 10 with the consequence', () => {
    expect(spfLookupRow(null, true)).toEqual([]);
    expect(spfLookupRow(undefined, undefined)).toEqual([]);
    expect(spfLookupRow(5, true)).toEqual([['SPF lookups', 'good', '5 of 10']]);
    expect(spfLookupRow(8, true)[0][1]).toBe('needs_work');
    expect(spfLookupRow(10, true)[0][1]).toBe('needs_work');
    const over = spfLookupRow(12, true)[0];
    expect(over[1]).toBe('missing');
    expect(over[2]).toContain('receivers treat SPF as failed');
  });

  it('labels a count that could not be completed as a minimum and never calls it fine', () => {
    const r = spfLookupRow(4, false)[0];
    expect(r[1]).toBe('unknown');
    expect(r[2]).toContain('at least 4 of 10');
    expect(r[2]).toContain('could not be read');
    expect(spfLookupRow(11, false)[0][1]).toBe('missing');
  });

  it('appears on the report card with the count the server gave', async () => {
    card = {
      domain: 'acme.com', days: 30, total: 200, pass_rate: 95, policy: 'none', spf_lookups: 9, spf_lookups_complete: true,
      posture: { domain: 'acme.com', status: 'good', mx: ['mx.acme.com'], mail_provider: null, spf: { status: 'good', summary: 'ok', record: null, issues: [] }, dmarc: { status: 'good', summary: 'ok', record: null, issues: [] }, dkim: { status: 'good', summary: 'ok', record: null, issues: [] } },
      advice: [],
    };
    render(view());
    await userEvent.click(await screen.findByRole('button', { name: 'acme.com' }));
    const shown = await screen.findByTestId('report-card');
    expect(within(shown).getByTestId('card-spf-lookups')).toHaveTextContent('9 of 10');
    expect(within(shown).getByTestId('card-spf-lookups')).toHaveClass('text-amber-300');
  });
});

describe('the MTA-STS row', () => {
  const sts = (o: Record<string, unknown>) => ({ state: 'ok', mode: 'enforce', max_age: 604800, mx_patterns: [], uncovered_mx: [], issues: [], ...o }) as never;
  it('says nothing without an answer, and mentions a missing policy only for a domain that receives mail', () => {
    expect(mtaStsRow(undefined, true)).toEqual([]);
    expect(mtaStsRow(sts({ state: 'none', mode: null, max_age: null }), false)).toEqual([]);
    expect(mtaStsRow(sts({ state: 'none', mode: null, max_age: null }), true)[0]).toEqual(['MTA-STS', 'needs_work', 'No policy published']);
  });
  it('is green for a clean enforced policy and red when an enforced one misses a real mail server', () => {
    expect(mtaStsRow(sts({}), true)[0]).toEqual(['MTA-STS', 'good', 'Enforced, remembered 7 days']);
    const red = mtaStsRow(sts({ uncovered_mx: ['mx2.acme.com'] }), true)[0];
    expect(red[1]).toBe('missing');
    expect(red[2]).toContain('mx2.acme.com');
  });
  it('calls testing and an unreadable policy what they are, never fine', () => {
    expect(mtaStsRow(sts({ mode: 'testing', max_age: 600 }), true)[0]).toEqual(['MTA-STS', 'needs_work', 'Testing only, remembered under a day']);
    expect(mtaStsRow(sts({ state: 'unreadable', mode: null }), true)[0][1]).toBe('unknown');
  });
});

describe('the policy progress panel', () => {
  const progress = [
    { client_id: 'c1', client_name: 'Acme Dental', domains: 3, rejecting: 0, quarantining: 1, monitoring: 2, ready_to_enforce: 1 },
    { client_id: 'c2', client_name: 'Birch Law', domains: 1, rejecting: 1, quarantining: 0, monitoring: 0, ready_to_enforce: 0 },
  ];
  it('says how many domains enforce overall, and gives each client its counts, amber only where one is ready', () => {
    render(<PolicyProgressPanel progress={progress} />);
    expect(screen.getByTestId('policy-progress')).toHaveTextContent('2 of 4 domains enforce (quarantine or reject); 1 still monitoring is ready to start enforcing.');
    const rows = screen.getAllByTestId('policy-progress-row');
    expect(rows.map((r) => r.textContent)).toEqual(['Acme Dental30121', 'Birch Law11000']);
    expect(within(rows[0]!).getAllByRole('cell')[5]).toHaveClass('text-amber-300');
    expect(within(rows[1]!).getAllByRole('cell')[5]).not.toHaveClass('text-amber-300');
  });
  it('shows nothing for a server that sends no progress or none', () => {
    const { container, rerender } = render(<PolicyProgressPanel progress={undefined} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<PolicyProgressPanel progress={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
  it('appears on the Results tab from the overview', async () => {
    overview = { days: 30, status, domains: [row()], progress };
    render(view());
    expect(await screen.findByTestId('policy-progress')).toBeInTheDocument();
  });
});
