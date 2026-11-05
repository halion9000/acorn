import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ManagedTenantRow, MsspOverview } from '@/lib/api';

const unmapped = vi.hoisted(() => ({ n: 0 }));
const overviewMock = vi.fn();
const tenantsMock = vi.fn();
const createClientMock = vi.fn();
const hiddenMock = vi.fn();
const playbooksMock = vi.fn();
const staleExemptMock = vi.fn();
vi.mock('@/lib/api', () => ({
  msspApi: { overview: () => overviewMock(), tenants: (h?: boolean) => tenantsMock(h), setClientHidden: (...a: unknown[]) => hiddenMock(...a), setPlaybookAutomation: (...a: unknown[]) => playbooksMock(...a), setStaleExempt: (...a: unknown[]) => staleExemptMock(...a), clients: async () => ({ clients: [], unmapped: unmapped.n }), createClient: (n: string) => createClientMock(n) },
}));
vi.mock('react-hot-toast', () => ({ default: { success: vi.fn(), error: vi.fn() } }));
const push = vi.hoisted(() => vi.fn());
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));

import toast from 'react-hot-toast';
import { orderSources } from './VendorBadge';
import MSSPDashboardView, { figure, matchesFilter, postureHref, tenantsToCsv, trendPath } from './MSSPDashboardView';

// The page used to render six invented tenants ("Acme Financial", "GlobalRetail Corp", ...) with invented alert counts, ARR and analyst
// allocation to every workspace, and an "Export Report" button that only showed a toast. These tests pin that it shows real data or an honest
// empty state, never a made-up number, and that Export really exports.
const INVENTED = ['Acme Financial', 'GlobalRetail Corp', 'MedSecure Health', 'NovaTech Industries', 'Pinnacle Energy', 'Stratos Logistics'];

const none: MsspOverview = {
  total_tenants: 0, tenants_reporting: 0, total_open_alerts: null, total_critical_alerts: null, total_open_cases: null, avg_health_score: null, avg_mttr_minutes: null, sla_breach_count: null,
};

function row(over: Partial<ManagedTenantRow> & { name: string }): ManagedTenantRow {
  return {
    tenant_id: `id-${over.name}`, has_metrics: false, snapshot_at: null, health_score: null, open_alerts: null, critical_alerts: null, open_cases: null, mttr_minutes: null, sla_breaches: null, connector_count: null, ...over,
  };
}

const reporting = row({ name: 'Reporting Co', has_metrics: true, snapshot_at: '2026-10-07T12:00:00Z', open_alerts: 12, critical_alerts: 2, open_cases: 4, mttr_minutes: 30, sla_breaches: 1, connector_count: 3, health_score: 80 });
const quiet = row({ name: 'Quiet Co' });
const healthy = row({ name: 'Healthy Co', has_metrics: true, snapshot_at: '2026-10-07T12:00:00Z', open_alerts: 0, critical_alerts: 0, open_cases: 0, mttr_minutes: 10, sla_breaches: 0, connector_count: 1, health_score: 99 });

beforeEach(() => {
  overviewMock.mockReset();
  tenantsMock.mockReset();
  createClientMock.mockReset();
  hiddenMock.mockReset();
  playbooksMock.mockReset();
  playbooksMock.mockResolvedValue(undefined);
  hiddenMock.mockResolvedValue(undefined);
  unmapped.n = 0;
  push.mockReset();
});

describe('the client mapping (it moved to Settings)', () => {
  it('has a button to the mapping page and no mapping section of its own', async () => {
    overviewMock.mockResolvedValue(none);
    tenantsMock.mockResolvedValue([reporting]);
    render(<MSSPDashboardView />);
    const link = await screen.findByRole('link', { name: 'Client mapping' });
    expect(link).toHaveAttribute('href', '/settings/client-mapping');
    expect(screen.queryByText(/Unmapped/i)).not.toBeInTheDocument();
  });

  it('warns at the top when tool clients are not linked yet, and says nothing when all are', async () => {
    overviewMock.mockResolvedValue(none);
    tenantsMock.mockResolvedValue([reporting]);
    unmapped.n = 3;
    const { unmount } = render(<MSSPDashboardView />);
    const banner = await screen.findByTestId('unlinked-banner');
    expect(banner).toHaveTextContent('3 tool clients are not linked');
    expect(within(banner).getByRole('link', { name: /Link them in Settings/ })).toHaveAttribute('href', '/settings/client-mapping');
    unmount();
    unmapped.n = 0;
    render(<MSSPDashboardView />);
    await screen.findByText('Reporting Co');
    expect(screen.queryByTestId('unlinked-banner')).not.toBeInTheDocument();
  });
});

describe('a workspace with no child tenants (the reported case)', () => {
  it('shows an honest empty state, none of the invented tenants, and no made-up figures', async () => {
    overviewMock.mockResolvedValue(none);
    tenantsMock.mockResolvedValue([]);
    const { container } = render(<MSSPDashboardView />);

    expect(await screen.findByText('No managed tenants yet')).toBeInTheDocument();
    for (const name of INVENTED) expect(container.textContent).not.toContain(name);
    expect(screen.getByText('0 reporting metrics')).toBeInTheDocument();
    // the totals nobody has reported are dashes, not zeros
    expect(screen.getAllByText('—').length).toBe(5);
    expect(container.textContent).not.toMatch(/ARR|\$\d/);
  });
});

describe('real tenants', () => {
  it('lists each tenant, with dashes and "No data yet" where nothing has been reported', async () => {
    overviewMock.mockResolvedValue({ ...none, total_tenants: 2, tenants_reporting: 1, total_open_alerts: 12, total_critical_alerts: 2, total_open_cases: 4, sla_breach_count: 1, avg_mttr_minutes: 30 });
    tenantsMock.mockResolvedValue([reporting, quiet]);
    render(<MSSPDashboardView />);

    const table = await screen.findByRole('table');
    const reportingRow = within(table).getByText('Reporting Co').closest('tr') as HTMLElement;
    expect(within(reportingRow).getAllByRole('cell').map((c) => c.textContent).slice(2, 13)).toEqual(['12', '2', '4', '30', '1', '3', '—', '—', '—', '—', '80']); // the dashes are the connector health, the due-soon alerts, the unreviewed tools and the stale alerts: this older row carries no reading of either
    const quietRow = within(table).getByText('Quiet Co').closest('tr') as HTMLElement;
    expect(within(quietRow).getAllByRole('cell').map((c) => c.textContent).slice(1)).toEqual(['—', '—', '—', '—', '—', '—', '—', '—', '—', '—', '—', '—', 'No data yet', '', '', 'Hide']); // the empty cells are the keep-alerts-open and automated-playbooks checkboxes
  });

  it('shows a real zero as 0 and an unreported figure as a dash: they are not the same thing', async () => {
    overviewMock.mockResolvedValue({ ...none, total_tenants: 2, tenants_reporting: 1, total_open_alerts: 0, total_critical_alerts: 0, total_open_cases: 0, sla_breach_count: 0, avg_mttr_minutes: 10 });
    tenantsMock.mockResolvedValue([healthy, quiet]);
    render(<MSSPDashboardView />);
    const table = await screen.findByRole('table');
    expect(within(within(table).getByText('Healthy Co').closest('tr') as HTMLElement).getAllByRole('cell')[2].textContent).toBe('0');
    expect(within(within(table).getByText('Quiet Co').closest('tr') as HTMLElement).getAllByRole('cell')[2].textContent).toBe('—');
  });

  it('has no ARR or analyst-allocation columns (there is no source for either)', async () => {
    overviewMock.mockResolvedValue({ ...none, total_tenants: 1 });
    tenantsMock.mockResolvedValue([quiet]);
    render(<MSSPDashboardView />);
    const headerCells = await within(await screen.findByRole('table')).findAllByRole('columnheader');
    expect(headerCells.every((h) => h.getAttribute('scope') === 'col'), 'every header cell says it heads a column').toBe(true);
    const headers = headerCells.map((h) => h.textContent);
    expect(headers).not.toContain('ARR');
    expect(headers).not.toContain('Analysts');
    expect(headers).not.toContain('MTTD (min)');
  });
});

describe('the figures at the top', () => {
  it('each opens the page that lists what it counts, with the matching filter', async () => {
    overviewMock.mockResolvedValue({ ...none, total_tenants: 2, tenants_reporting: 1, total_open_alerts: 12, total_critical_alerts: 2, total_open_cases: 4, sla_breach_count: 1, avg_mttr_minutes: 30 });
    tenantsMock.mockResolvedValue([reporting, quiet]);
    render(<MSSPDashboardView />);
    await screen.findByRole('table');
    const href = (name: RegExp) => screen.getByRole('link', { name }).getAttribute('href');
    expect(href(/^Open alerts/)).toBe('/alerts?status=open');
    expect(href(/^Critical alerts/)).toBe('/alerts?status=open&severity=critical');
    expect(href(/^Open cases/)).toBe('/cases?scope=all');
    expect(href(/^SLA breaches/)).toBe('/sla');
    expect(href(/^Avg MTTR/)).toBe('/sla');
    expect(href(/^Managed tenants/)).toBe('#tenant-overview');
    expect(document.getElementById('tenant-overview')).not.toBeNull();
  });
});

describe('filters', () => {
  it('shows only tenants breaching their SLA, or only those with no data yet', async () => {
    overviewMock.mockResolvedValue({ ...none, total_tenants: 3 });
    tenantsMock.mockResolvedValue([reporting, quiet, healthy]);
    render(<MSSPDashboardView />);
    const user = userEvent.setup();
    const table = await screen.findByRole('table'); // the table only: the merge picker below lists every client, filtered or not

    await user.click(screen.getByRole('button', { name: 'Breaching SLA' }));
    expect(within(table).getByText('Reporting Co')).toBeInTheDocument();
    expect(within(table).queryByText('Healthy Co')).not.toBeInTheDocument();
    expect(within(table).queryByText('Quiet Co')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'No data yet' }));
    expect(within(table).getByText('Quiet Co')).toBeInTheDocument();
    expect(within(table).queryByText('Reporting Co')).not.toBeInTheDocument();
  });

  it('offers a way back when a filter matches nothing', async () => {
    overviewMock.mockResolvedValue({ ...none, total_tenants: 1 });
    tenantsMock.mockResolvedValue([healthy]);
    render(<MSSPDashboardView />);
    const user = userEvent.setup();
    await screen.findByRole('table');
    await user.click(screen.getByRole('button', { name: 'Breaching SLA' }));
    expect(screen.getByText('No tenants match this filter')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Show all tenants' }));
    expect(screen.getByText('Healthy Co')).toBeInTheDocument();
  });

  it('matchesFilter treats a tenant with no metrics as not breaching', () => {
    expect(matchesFilter(quiet, 'breaching')).toBe(false);
    expect(matchesFilter(quiet, 'no-data')).toBe(true);
    expect(matchesFilter(reporting, 'breaching')).toBe(true);
    expect(matchesFilter(healthy, 'breaching')).toBe(false);
  });
});

describe('loading and errors', () => {
  it('says it is loading, then shows the data', async () => {
    let finish: (rows: ManagedTenantRow[]) => void = () => undefined;
    overviewMock.mockResolvedValue({ ...none, total_tenants: 1 });
    tenantsMock.mockReturnValue(new Promise<ManagedTenantRow[]>((resolve) => (finish = resolve)));
    render(<MSSPDashboardView />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading managed tenants');
    finish([quiet]);
    expect(await screen.findByText('Quiet Co')).toBeInTheDocument();
  });

  it('shows the failure instead of falling back to sample data, and retries', async () => {
    overviewMock.mockRejectedValueOnce(new Error('403 forbidden: missing mssp:read')).mockResolvedValue({ ...none, total_tenants: 1 });
    tenantsMock.mockResolvedValue([quiet]);
    const { container } = render(<MSSPDashboardView />);
    expect(await screen.findByText('Could not load managed tenants')).toBeInTheDocument();
    expect(screen.getByText('403 forbidden: missing mssp:read')).toBeInTheDocument();
    for (const name of INVENTED) expect(container.textContent).not.toContain(name);
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('Quiet Co')).toBeInTheDocument();
  });
});

describe('Export CSV really exports', () => {
  it('builds a CSV with a header, blank cells for unreported figures, and safe quoting', () => {
    const csv = tenantsToCsv([reporting, quiet, row({ name: 'Smith, "Jones" & Co' })]);
    const lines = csv.trimEnd().split('\n');
    expect(lines[0]).toBe('tenant,tenant_id,has_metrics,snapshot_at,open_alerts,critical_alerts,open_cases,mttr_minutes,sla_breaches,connector_count,health_score');
    expect(lines[1]).toBe('Reporting Co,id-Reporting Co,yes,2026-10-07T12:00:00Z,12,2,4,30,1,3,80');
    expect(lines[2]).toBe('Quiet Co,id-Quiet Co,no,,,,,,,,');
    // a comma or a double quote forces quoting, and a quote inside a quoted cell is doubled
    expect(lines[3]).toBe('"Smith, ""Jones"" & Co","id-Smith, ""Jones"" & Co",no,,,,,,,,');
  });

  it('writes a tenant name that a spreadsheet would run as a formula as plain text', () => {
    const csv = tenantsToCsv([row({ name: '=HYPERLINK("http://evil.example","open")' }), row({ name: '@SUM(1+1)' }), row({ name: '-2+3' }), row({ name: 'Fine Co' })]);
    const lines = csv.trimEnd().split('\n');
    expect(lines[1].startsWith(`"'=HYPERLINK(""http://evil.example"",""open"")",`)).toBe(true);
    expect(lines[2].startsWith("'@SUM(1+1),")).toBe(true);
    expect(lines[3].startsWith("'-2+3,")).toBe(true);
    expect(lines[4].startsWith('Fine Co,')).toBe(true);
  });

  it('downloads the rows on screen when clicked, and is disabled when there are none', async () => {
    const created: Blob[] = [];
    const createObjectURL = vi.fn((blob: Blob) => (created.push(blob), 'blob:test'));
    Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);

    overviewMock.mockResolvedValue({ ...none, total_tenants: 2 });
    tenantsMock.mockResolvedValue([reporting, quiet]);
    const view = render(<MSSPDashboardView />);
    const user = userEvent.setup();
    await screen.findByRole('table');
    await user.click(screen.getByRole('button', { name: 'No data yet' }));
    await user.click(screen.getByRole('button', { name: 'Export CSV' }));

    expect(click).toHaveBeenCalledTimes(1);
    const text = await created[0].text();
    expect(text).toContain('Quiet Co');
    expect(text).not.toContain('Reporting Co'); // exports what is filtered on screen
    view.unmount();

    tenantsMock.mockResolvedValue([]);
    overviewMock.mockResolvedValue(none);
    render(<MSSPDashboardView />);
    await screen.findByText('No managed tenants yet');
    expect(screen.getByRole('button', { name: 'Export CSV' })).toBeDisabled();
    click.mockRestore();
  });
});

describe('figure()', () => {
  it('is a dash for anything unreported, and formats real numbers', () => {
    expect(figure(null)).toBe('—');
    expect(figure(undefined)).toBe('—');
    expect(figure(Number.NaN)).toBe('—');
    expect(figure(0)).toBe('0');
    expect(figure(30.4, { decimals: 0, suffix: ' min' })).toBe('30 min');
  });
});

describe('adding a client by hand (the reported gap)', () => {
  it('creates the client, then reloads the table so it shows up', async () => {
    overviewMock.mockResolvedValue(none);
    tenantsMock.mockResolvedValueOnce([]).mockResolvedValue([row({ name: 'Acme Dental' })]);
    createClientMock.mockResolvedValue({ id: 'x', name: 'Acme Dental' });
    const user = userEvent.setup();
    render(<MSSPDashboardView />);

    await screen.findByText('No managed tenants yet');
    await user.click(screen.getByRole('button', { name: 'Add client' }));
    await user.type(screen.getByLabelText('Client name'), '  Acme Dental ');
    await user.click(screen.getByRole('button', { name: 'Create' }));

    expect(createClientMock).toHaveBeenCalledWith('Acme Dental');
    expect(await screen.findByText('Acme Dental')).toBeInTheDocument();
  });

  it('will not create a client with a blank name', async () => {
    overviewMock.mockResolvedValue(none);
    tenantsMock.mockResolvedValue([]);
    const user = userEvent.setup();
    render(<MSSPDashboardView />);

    await screen.findByText('No managed tenants yet');
    await user.click(screen.getByRole('button', { name: 'Add client' }));
    await user.type(screen.getByLabelText('Client name'), '   ');
    expect(screen.getByRole('button', { name: 'Create' })).toBeDisabled();
    expect(createClientMock).not.toHaveBeenCalled();
  });
});

describe('the automated playbooks column', () => {
  it('shows the choice for each client, off unless the server says on, and saves a change', async () => {
    overviewMock.mockResolvedValue({ ...none, total_tenants: 2 });
    tenantsMock.mockResolvedValue([row({ name: 'Acme' }), row({ name: 'Beta', playbook_automation: true })]);
    const user = userEvent.setup();
    render(<MSSPDashboardView />);
    const acme = await screen.findByRole('checkbox', { name: 'Allow automated playbooks for Acme' });
    const beta = screen.getByRole('checkbox', { name: 'Allow automated playbooks for Beta' });
    expect(acme).not.toBeChecked();
    expect(beta).toBeChecked();
    expect(screen.getByText(/playbooks do not start by themselves yet/)).toBeInTheDocument();
    await user.click(acme);
    expect(playbooksMock).toHaveBeenCalledWith('id-Acme', true);
    expect(acme).toBeChecked();
    await user.click(beta);
    expect(playbooksMock).toHaveBeenCalledWith('id-Beta', false);
    expect(beta).not.toBeChecked();
  });

  it('puts the box back and says so when the change cannot be saved', async () => {
    overviewMock.mockResolvedValue({ ...none, total_tenants: 1 });
    tenantsMock.mockResolvedValue([row({ name: 'Acme' })]);
    playbooksMock.mockRejectedValue(new Error('Permission denied: mssp:manage'));
    const user = userEvent.setup();
    render(<MSSPDashboardView />);
    const acme = await screen.findByRole('checkbox', { name: 'Allow automated playbooks for Acme' });
    await user.click(acme);
    await waitFor(() => expect(acme).not.toBeChecked());
    expect(toast.error).toHaveBeenCalledWith('Permission denied: mssp:manage');
  });
});

describe('the keep alerts open column', () => {
  it('shows the choice per client, off unless the server says on, and saves a change', async () => {
    overviewMock.mockResolvedValue({ ...none, total_tenants: 2 });
    tenantsMock.mockResolvedValue([row({ name: 'Acme' }), row({ name: 'Beta', stale_exempt: true })]);
    const user = userEvent.setup();
    render(<MSSPDashboardView />);
    const acme = await screen.findByRole('checkbox', { name: 'Never set aside stale alerts for Acme' });
    const beta = screen.getByRole('checkbox', { name: 'Never set aside stale alerts for Beta' });
    expect(acme).not.toBeChecked();
    expect(beta).toBeChecked();
    await user.click(acme);
    expect(staleExemptMock).toHaveBeenCalledWith('id-Acme', true);
    expect(acme).toBeChecked();
    await user.click(beta);
    expect(staleExemptMock).toHaveBeenCalledWith('id-Beta', false);
    expect(beta).not.toBeChecked();
  });

  it('puts the box back and says so when the change cannot be saved', async () => {
    overviewMock.mockResolvedValue({ ...none, total_tenants: 1 });
    tenantsMock.mockResolvedValue([row({ name: 'Acme' })]);
    staleExemptMock.mockRejectedValue(new Error('Permission denied: mssp:manage'));
    const user = userEvent.setup();
    render(<MSSPDashboardView />);
    const acme = await screen.findByRole('checkbox', { name: 'Never set aside stale alerts for Acme' });
    await user.click(acme);
    await waitFor(() => expect(acme).not.toBeChecked());
    expect(toast.error).toHaveBeenCalledWith('Permission denied: mssp:manage');
  });
});

describe('hiding test clients', () => {
  it('hides a tenant from its row, and "Show hidden" asks the server for the hidden ones too', async () => {
    overviewMock.mockResolvedValue({ ...none, total_tenants: 1 });
    tenantsMock.mockImplementation(async (h?: boolean) => (h ? [row({ name: 'Real Co' }), row({ name: 'Hal Test', hidden: true })] : [row({ name: 'Real Co' })]));
    const user = userEvent.setup();
    render(<MSSPDashboardView />);

    await screen.findByText('Real Co');
    expect(screen.queryByText('Hal Test')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Hide' }));
    expect(hiddenMock).toHaveBeenCalledWith('id-Real Co', true);

    await user.click(screen.getByLabelText('Show hidden'));
    expect(await screen.findByText('Hal Test')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Show' }));
    expect(hiddenMock).toHaveBeenCalledWith('id-Hal Test', false);
  });
});

describe('the Integrations column', () => {
  it('shows a badge per tool a tenant is mapped from, and a dash when none', async () => {
    overviewMock.mockResolvedValue({ ...none, total_tenants: 2 });
    tenantsMock.mockResolvedValue([row({ name: 'Two Tools', sources: ['halopsa', 'huntress'] }), row({ name: 'No Tools' })]);
    render(<MSSPDashboardView />);
    const table = await screen.findByRole('table');
    expect(within(table).getByRole('columnheader', { name: 'Integrations' })).toBeInTheDocument();
    const two = within(table).getByText('Two Tools').closest('tr') as HTMLElement;
    expect(within(two).getByRole('img', { name: 'HaloPSA' })).toBeInTheDocument();
    expect(within(two).getByRole('img', { name: 'Huntress' })).toBeInTheDocument();
    const none0 = within(table).getByText('No Tools').closest('tr') as HTMLElement;
    expect(within(none0).queryByRole('img')).toBeNull();
  });
});

describe('the Integrations column order', () => {
  it('renders Halo first then the others in a fixed order whatever order the API sends', async () => {
    overviewMock.mockResolvedValue({ ...none, total_tenants: 1 });
    tenantsMock.mockResolvedValue([row({ name: 'Mixed', sources: ['addigy', 'huntress', 'halopsa', 'ninjaone'] })]);
    render(<MSSPDashboardView />);
    const table = await screen.findByRole('table');
    const tr = within(table).getByText('Mixed').closest('tr') as HTMLElement;
    expect(within(tr).getAllByRole('img').map((i) => i.getAttribute('alt'))).toEqual(['HaloPSA', 'NinjaOne', 'Huntress', 'Addigy']);
  });
});

describe('the Integrations column layout', () => {
  it('lays the tool icons out four to a row however narrow the column gets, and shows a dash for a client with none', async () => {
    overviewMock.mockResolvedValue({ ...none, total_tenants: 2 });
    tenantsMock.mockResolvedValue([row({ name: 'Many', sources: ['halopsa', 'ninjaone', 'huntress', 'addigy', 'blumira', 'petra', 'liongard'] }), row({ name: 'None' })]);
    render(<MSSPDashboardView />);
    const table = await screen.findByRole('table');
    const many = within(within(table).getByText('Many').closest('tr') as HTMLElement).getByTestId('sources');
    // four columns of the icon's own width, rows no taller than the icons: the table cell can be as narrow or as tall as it likes without squeezing or stretching them
    expect(many).toHaveClass('grid-cols-[repeat(4,1.5rem)]', 'content-start', 'items-center');
    expect(many).not.toHaveClass('flex');
    expect(within(many).getAllByRole('img')).toHaveLength(7);
    expect(within(within(table).getByText('None').closest('tr') as HTMLElement).getByTestId('sources')).toHaveTextContent('—');
  });
});

describe('the tenant table fits the window', () => {
  it('uses the narrow cell padding on every cell of its 17 columns, so the page does not need sideways scrolling', async () => {
    overviewMock.mockResolvedValue({ ...none, total_tenants: 1 });
    tenantsMock.mockResolvedValue([row({ name: 'One', sources: ['halopsa'] })]);
    render(<MSSPDashboardView />);
    const table = await screen.findByRole('table');
    const cells = [...table.querySelectorAll('th, td')];
    expect(cells).toHaveLength(34);
    expect(cells.filter((c) => !c.className.includes('px-2.5'))).toEqual([]);
  });
});

describe('orderSources', () => {
  it('puts halo first and keeps one fixed order for the rest', () => {
    expect(orderSources(['addigy', 'huntress', 'zzz', 'halopsa', 'ninjaone', 'threatmate'])).toEqual([
      'halopsa',
      'ninjaone',
      'huntress',
      'threatmate',
      'addigy',
      'zzz',
    ]);
  });
});

describe('a client line opens its Client Posture page', () => {
  it('has the name as a link and opens the posture when the line itself is clicked, but not when a control inside it is', async () => {
    overviewMock.mockResolvedValue(none);
    tenantsMock.mockResolvedValue([reporting, quiet]);
    render(<MSSPDashboardView />);
    const lines = await screen.findAllByTestId('client-line');
    expect(within(lines[0]).getByRole('link', { name: 'Reporting Co' })).toHaveAttribute('href', '/settings/client-posture?client=id-Reporting%20Co');
    await userEvent.click(within(lines[0]).getAllByRole('cell')[1]);
    expect(push).toHaveBeenCalledWith('/settings/client-posture?client=id-Reporting%20Co');
    push.mockReset();
    await userEvent.click(within(lines[0]).getAllByRole('checkbox')[0]);
    expect(push).not.toHaveBeenCalled();
  });

  it('postureHref escapes the id', () => {
    expect(postureHref('a b/c')).toBe('/settings/client-posture?client=a%20b%2Fc');
  });
});

describe('connector health per client', () => {
  it('shows the failing count in red, all ok when none fail, none when there are none, and a dash when unknown', async () => {
    overviewMock.mockResolvedValue(none);
    tenantsMock.mockResolvedValue([
      row({ name: 'Failing Co', connectors_enabled: 4, connectors_unhealthy: 2 }),
      row({ name: 'Fine Co', connectors_enabled: 3, connectors_unhealthy: 0 }),
      row({ name: 'Empty Co', connectors_enabled: 0, connectors_unhealthy: 0 }),
      row({ name: 'Unknown Co', connectors_enabled: null, connectors_unhealthy: null }),
    ]);
    render(<MSSPDashboardView />);
    await screen.findByText('Failing Co');
    const cells = Object.fromEntries(screen.getAllByTestId('client-line').map((l) => [l.querySelector('a')?.textContent, within(l).getByTestId('connector-health')]));
    expect(cells['Failing Co']).toHaveTextContent('2 of 4 failing');
    expect(cells['Failing Co']).toHaveClass('text-red-400');
    expect(cells['Fine Co']).toHaveTextContent('all 3 ok');
    expect(cells['Fine Co']).not.toHaveClass('text-red-400');
    expect(cells['Empty Co']).toHaveTextContent('none');
    expect(cells['Unknown Co']).toHaveTextContent('—');
  });

  it('reads a server that does not send the fields as unknown, not as healthy', async () => {
    overviewMock.mockResolvedValue(none);
    tenantsMock.mockResolvedValue([row({ name: 'Old Server Co' })]);
    render(<MSSPDashboardView />);
    await screen.findByText('Old Server Co');
    expect(screen.getByTestId('connector-health')).toHaveTextContent('—');
  });
});

describe('stale alerts per client', () => {
  it('shows the count per client, zero as 0, and a dash when it is unknown or the server does not send it', async () => {
    overviewMock.mockResolvedValue(none);
    tenantsMock.mockResolvedValue([row({ name: 'Many Co', stale_alerts: 12 }), row({ name: 'Zero Co', stale_alerts: 0 }), row({ name: 'Unknown Co', stale_alerts: null }), row({ name: 'Old Server Co' })]);
    render(<MSSPDashboardView />);
    await screen.findByText('Many Co');
    const cells = Object.fromEntries(screen.getAllByTestId('client-line').map((l) => [l.querySelector('a')?.textContent, within(l).getByTestId('stale-alerts').textContent]));
    expect(cells).toEqual({ 'Many Co': '12', 'Zero Co': '0', 'Unknown Co': '—', 'Old Server Co': '—' });
  });
});

describe('unreviewed remote tools per client', () => {
  it('shows the count, amber when there are some, and a dash when unknown or not sent', async () => {
    overviewMock.mockResolvedValue(none);
    tenantsMock.mockResolvedValue([row({ name: 'Some Co', unreviewed_remote_tools: 3 }), row({ name: 'Zero Co', unreviewed_remote_tools: 0 }), row({ name: 'Unknown Co', unreviewed_remote_tools: null }), row({ name: 'Old Server Co' })]);
    render(<MSSPDashboardView />);
    await screen.findByText('Some Co');
    const cells = Object.fromEntries(screen.getAllByTestId('client-line').map((l) => [l.querySelector('a')?.textContent, within(l).getByTestId('unreviewed-tools')]));
    expect(Object.fromEntries(Object.entries(cells).map(([k, v]) => [k, v.textContent]))).toEqual({ 'Some Co': '3', 'Zero Co': '0', 'Unknown Co': '—', 'Old Server Co': '—' });
    expect(cells['Some Co']).toHaveClass('text-amber-300');
    expect(cells['Zero Co']).not.toHaveClass('text-amber-300');
  });
});

describe('the health trend', () => {
  it('draws a line from two points on, red when the score fell and green when it rose, and nothing otherwise', async () => {
    overviewMock.mockResolvedValue(none);
    tenantsMock.mockResolvedValue([
      row({ name: 'Falling Co', health_score: 60, health_trend: [90, 75, 60] }),
      row({ name: 'Rising Co', health_score: 90, health_trend: [60, 90] }),
      row({ name: 'One Point Co', health_score: 80, health_trend: [80] }),
      row({ name: 'Empty Co', health_trend: [] }),
      row({ name: 'Unknown Co', health_trend: null }),
      row({ name: 'Old Server Co' }),
    ]);
    render(<MSSPDashboardView />);
    await screen.findByText('Falling Co');
    const lines = Object.fromEntries(screen.getAllByTestId('client-line').map((l) => [l.querySelector('a')?.textContent, within(l).queryByTestId('health-trend')]));
    expect(lines['Falling Co']).toHaveClass('text-red-400');
    expect(lines['Falling Co']).toHaveAttribute('aria-label', 'Health over the last two weeks: 90 to 60');
    expect(lines['Rising Co']).toHaveClass('text-green-400');
    for (const none of ['One Point Co', 'Empty Co', 'Unknown Co', 'Old Server Co']) expect(lines[none]).toBeNull();
  });
  it('scales the path into the box with the lowest point at the bottom, and is empty for fewer than two points', () => {
    expect(trendPath([])).toBe('');
    expect(trendPath([5])).toBe('');
    expect(trendPath([0, 10], 56, 16)).toBe('M0.0,15.0 L56.0,1.0');
    expect(trendPath([7, 7], 56, 16)).toBe('M0.0,15.0 L56.0,15.0');
  });
});

describe('alerts due soon per client', () => {
  it('shows the count, amber when some are about to breach, and a dash when unknown or not sent', async () => {
    overviewMock.mockResolvedValue(none);
    tenantsMock.mockResolvedValue([row({ name: 'Some Co', sla_due_soon: 3 }), row({ name: 'Zero Co', sla_due_soon: 0 }), row({ name: 'Unknown Co', sla_due_soon: null }), row({ name: 'Old Server Co' })]);
    render(<MSSPDashboardView />);
    await screen.findByText('Some Co');
    const cells = Object.fromEntries(screen.getAllByTestId('client-line').map((l) => [l.querySelector('a')?.textContent, within(l).getByTestId('sla-due-soon')]));
    expect(Object.fromEntries(Object.entries(cells).map(([k, v]) => [k, v.textContent]))).toEqual({ 'Some Co': '3', 'Zero Co': '0', 'Unknown Co': '—', 'Old Server Co': '—' });
    expect(cells['Some Co']).toHaveClass('text-amber-300');
    expect(cells['Zero Co']).not.toHaveClass('text-amber-300');
  });
});
