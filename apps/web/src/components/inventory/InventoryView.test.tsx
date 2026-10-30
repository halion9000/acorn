import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const api = vi.hoisted(() => ({ list: vi.fn(), create: vi.fn(), update: vi.fn(), checkOut: vi.fn(), checkIn: vi.fn(), events: vi.fn(), import: vi.fn(), exportCsv: vi.fn(), bulk: vi.fn(), syncDevices: vi.fn() }));
const mssp = vi.hoisted(() => ({ listChildren: vi.fn() }));
vi.mock('@/lib/api', () => ({ inventoryApi: api, msspApi: mssp }));

import { InventoryView, holderLabel } from './InventoryView';

const item = (over: Record<string, unknown> = {}) => ({
  id: 'i1', kind: 'stock', client_id: 'c1', client_name: 'Acme Dental', customer_name: 'Acme Dental', name: 'Dell Pro Max 16', category: 'Computers', serial: 'BSH7SB4', model: 'Pro Max 16', manufacturer: null,
  quantity: 1, status: 'checked_in', site: null, person: null, part_no: null, has_charger: null, cpu: null, memory: null, storage: null, ninja_url: null, accounting_treatment: null,
  deployed_at: null, redeployed_at: null, checked_out_at: null, checked_in_at: '2026-10-01', notes: null, tags: [], ticket_url: null, source: 'manual', updated_at: '2026-10-01T00:00:00Z', device: null, ...over,
});
const list = (items: unknown[], over: Record<string, unknown> = {}) => ({
  items, total: items.length, page: 1, pages: 1,
  summary: { total: items.length, by_status: { checked_in: 2, checked_out: 1 }, categories: [['Computers', 2], ['Drives', 1]], unmatched_customers: 0 }, ...over,
});

function view() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
      <InventoryView />
    </SWRConfig>,
  );
}
const lastQuery = () => api.list.mock.calls[api.list.mock.calls.length - 1][0];

beforeEach(() => {
  Object.values(api).forEach((m) => m.mockReset());
  mssp.listChildren.mockReset().mockResolvedValue([{ id: 'c1', name: 'Acme Dental' }, { id: 'c2', name: 'Birch Law' }]);
  api.list.mockResolvedValue(list([item()]));
});

describe('holderLabel', () => {
  it('names the client, marks a customer not yet matched, and calls an unowned item Live Oak\'s own', () => {
    expect(holderLabel({ client_name: 'Acme', customer_name: 'Acme Inc' })).toBe('Acme');
    expect(holderLabel({ client_name: null, customer_name: 'Unknown Co' })).toBe('Unknown Co (not matched)');
    expect(holderLabel({ client_name: null, customer_name: null })).toBe('Live Oak (own)');
  });
});

describe('InventoryView list', () => {
  it('shows each item with its client, serial, status and the count of each status', async () => {
    api.list.mockResolvedValue(list([item(), item({ id: 'i2', name: 'UPS', client_id: null, client_name: null, customer_name: null, serial: null, status: 'checked_out', person: 'Pat Jones', site: 'Austin', checked_out_at: '2026-10-05' })]));
    view();
    const rows = await screen.findAllByTestId('inventory-row');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('Dell Pro Max 16');
    expect(rows[0]).toHaveTextContent('Acme Dental');
    expect(rows[0]).toHaveTextContent('BSH7SB4');
    expect(rows[1]).toHaveTextContent('Live Oak (own)');
    expect(rows[1]).toHaveTextContent('Pat Jones · Austin');
    expect(screen.getByTestId('status-chips')).toHaveTextContent('Checked in 2');
    expect(screen.getByTestId('count')).toHaveTextContent('2 items');
  });

  it('links an item to the machine it is, and says so when a customer name was not matched to a client', async () => {
    api.list.mockResolvedValue(
      list([item({ device: { device_id: 'd1', hostname: 'AUSTIN-LAP-01', last_seen: '2026-10-30T00:00:00Z', how: 'serial' } })], { summary: { total: 1, by_status: {}, categories: [], unmatched_customers: 3 } }),
    );
    view();
    expect(await screen.findByTestId('device-link')).toHaveAttribute('href', '/devices?search=BSH7SB4');
    expect(screen.getByText('3 customer names are not matched to a client')).toBeInTheDocument();
  });

  it('asks the server for what the filters say and starts again at page one', async () => {
    view();
    await screen.findAllByTestId('inventory-row');
    await userEvent.selectOptions(screen.getByLabelText('Client'), 'own');
    await waitFor(() => expect(lastQuery()).toMatchObject({ kind: 'stock', client: 'own', page: 1 }));
    await userEvent.selectOptions(screen.getByLabelText('Client'), 'c2');
    await waitFor(() => expect(lastQuery().client).toBe('c2'));
    await userEvent.selectOptions(screen.getByLabelText('Category'), 'Drives');
    await waitFor(() => expect(lastQuery().category).toBe('Drives'));
    await userEvent.click(screen.getByRole('button', { name: /Checked out/ }));
    await waitFor(() => expect(lastQuery().status).toBe('checked_out'));
    await userEvent.type(screen.getByLabelText('Search inventory'), 'dock');
    await waitFor(() => expect(lastQuery().search).toBe('dock'));
  });

  it('switches to the NUC list with its own columns and drops the stock-only controls', async () => {
    view();
    await screen.findAllByTestId('inventory-row');
    await userEvent.click(screen.getByRole('tab', { name: 'NUCs' }));
    await waitFor(() => expect(lastQuery().kind).toBe('nuc'));
    expect(screen.getByRole('columnheader', { name: 'Computer' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Site and person' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Category')).toBeNull();
    expect(screen.getByRole('button', { name: 'Add a NUC' })).toBeInTheDocument();
  });

  it('says what is missing: nothing yet, nothing matching, or a failure to load', async () => {
    api.list.mockResolvedValue(list([], { summary: { total: 0, by_status: {}, categories: [], unmatched_customers: 0 } }));
    const first = view();
    expect(await screen.findByTestId('empty')).toHaveTextContent('Nothing here yet');
    first.unmount();
    api.list.mockResolvedValue(list([], { summary: { total: 5, by_status: {}, categories: [], unmatched_customers: 0 } }));
    const second = view();
    expect(await screen.findByTestId('empty')).toHaveTextContent('Nothing matches those filters');
    second.unmount();
    api.list.mockRejectedValue(new Error('boom'));
    view();
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load the inventory');
  });
});

describe('InventoryView actions', () => {
  it('checks an item out to a person with a ticket and a note, offering Check out only for an item that is here', async () => {
    api.list.mockResolvedValue(list([item(), item({ id: 'i2', name: 'Out one', status: 'checked_out', person: 'Pat' })]));
    api.checkOut.mockResolvedValue(item({ status: 'checked_out' }));
    view();
    const rows = await screen.findAllByTestId('inventory-row');
    expect(within(rows[1]).queryByRole('button', { name: 'Check out' })).toBeNull();
    expect(within(rows[1]).getByRole('button', { name: 'Check in' })).toBeInTheDocument();
    await userEvent.click(within(rows[0]).getByRole('button', { name: 'Check out' }));
    await userEvent.type(screen.getByLabelText('Who has it'), 'Pat Jones');
    await userEvent.type(screen.getByLabelText('Ticket link'), 'https://liveoakit.halopsa.com/tickets?id=9');
    await userEvent.type(screen.getByLabelText('Note'), 'new hire');
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Check out' }));
    await waitFor(() => expect(api.checkOut).toHaveBeenCalledWith('i1', { person: 'Pat Jones', site: undefined, ticket_url: 'https://liveoakit.halopsa.com/tickets?id=9', note: 'new hire' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('checks an item back in, and shows the API\'s reason when it refuses', async () => {
    api.list.mockResolvedValue(list([item({ status: 'checked_out', person: 'Pat' })]));
    api.checkIn.mockRejectedValueOnce(new Error('An item that is checked in cannot be checked in')).mockResolvedValueOnce(item());
    view();
    await userEvent.click(await screen.findByRole('button', { name: 'Check in' }));
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Check in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('cannot be checked in');
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Check in' }));
    await waitFor(() => expect(api.checkIn).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('shows an item\'s history newest first', async () => {
    api.events.mockResolvedValue([
      { id: 'e2', at: '2026-10-05T10:00:00Z', event: 'checked_out', actor: 'hal@goliveoak.com', person: 'Pat Jones', ticket_url: 'https://t/1', note: 'new hire' },
      { id: 'e1', at: '2026-10-01T10:00:00Z', event: 'created', actor: 'hal@goliveoak.com', person: null, ticket_url: null, note: null },
    ]);
    view();
    await userEvent.click(await screen.findByRole('button', { name: 'History' }));
    const history = await screen.findByTestId('history');
    expect(api.events).toHaveBeenCalledWith('i1');
    const entries = within(history).getAllByRole('listitem');
    expect(entries[0]).toHaveTextContent('checked out');
    expect(entries[0]).toHaveTextContent('With: Pat Jones');
    expect(entries[1]).toHaveTextContent('created');
  });

  it('adds an item for a chosen client, or for Live Oak when none is chosen', async () => {
    api.create.mockResolvedValue(item());
    view();
    await screen.findAllByTestId('inventory-row');
    await userEvent.click(screen.getByRole('button', { name: 'Add an item' }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByRole('button', { name: 'Add' })).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText('Name'), 'Spare dock');
    await userEvent.selectOptions(within(dialog).getByLabelText('Client'), 'c2');
    await userEvent.type(within(dialog).getByLabelText('Serial number'), 'DOCK0001');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add' }));
    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
    expect(api.create.mock.calls[0][0]).toMatchObject({ kind: 'stock', name: 'Spare dock', serial: 'DOCK0001', client_id: 'c2', quantity: 1, status: 'checked_in' });
    await userEvent.click(screen.getByRole('button', { name: 'Add an item' }));
    await userEvent.type(within(screen.getByRole('dialog')).getByLabelText('Name'), 'Cables');
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Add' }));
    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(2));
    expect(api.create.mock.calls[1][0]).not.toHaveProperty('client_id');
  });

  it('edits an item and moves it to Live Oak or to a client', async () => {
    api.update.mockResolvedValue(item());
    view();
    await userEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const dialog = screen.getByRole('dialog');
    await userEvent.selectOptions(within(dialog).getByLabelText('Client'), 'own');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.update).toHaveBeenCalledTimes(1));
    expect(api.update.mock.calls[0][1]).toMatchObject({ name: 'Dell Pro Max 16', move_to_own: true });
    expect(api.update.mock.calls[0][1]).not.toHaveProperty('client_id');
  });
});

describe('InventoryView import', () => {
  const preview = {
    dry_run: true, rows: 5, created: 4, updated: 0, skipped: 1, problems: ['line 6: no name, model or serial number'],
    customers: [
      { name: 'Acme Dental', rows: 2, placed: 'exact', client_id: 'c1', client_name: 'Acme Dental', suggestions: [] },
      { name: 'Birch Law Firm', rows: 2, placed: 'unmatched', client_id: null, client_name: null, suggestions: [{ client_id: 'c2', client_name: 'Birch Law', score: 0.85 }] },
    ],
  };

  it('previews where each customer would go, lets an unmatched one be placed, and imports with that choice', async () => {
    api.import.mockResolvedValueOnce(preview).mockResolvedValueOnce({ ...preview, dry_run: false, created: 4, updated: 0, skipped: 1 });
    view();
    await screen.findAllByTestId('inventory-row');
    await userEvent.click(screen.getByRole('button', { name: 'Import CSV' }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByRole('button', { name: 'Preview' })).toBeDisabled();
    const file = new File(['"ID","Customer","EntryName"\n"1","Acme Dental","Laptop"\n'], 'LO_Inventory.csv', { type: 'text/csv' });
    await userEvent.upload(within(dialog).getByLabelText('CSV file'), file);
    await userEvent.click(within(dialog).getByRole('button', { name: 'Preview' }));
    const shown = await screen.findByTestId('import-preview');
    expect(shown).toHaveTextContent('5 rows read');
    expect(api.import.mock.calls[0][0]).toMatchObject({ kind: 'stock', dry_run: true, mapping: {} });
    expect(api.import.mock.calls[0][0].csv_text).toContain('Acme Dental');
    const customers = within(shown).getAllByTestId('import-customer');
    expect(customers[0]).toHaveTextContent('Acme Dental');
    expect(customers[0]).toHaveTextContent('matched to a client');
    await userEvent.selectOptions(within(customers[1]).getByLabelText('Place Birch Law Firm'), 'c2');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Import' }));
    await waitFor(() => expect(api.import).toHaveBeenCalledTimes(2));
    expect(api.import.mock.calls[1][0]).toMatchObject({ dry_run: false, mapping: { 'birch law firm': 'c2' } });
    expect(await screen.findByTestId('import-result')).toHaveTextContent('Done: 4 added, 0 updated, 1 left out.');
  });

  it('sends the client chosen for a whole per-client file, and shows the API\'s message when a file cannot be read', async () => {
    api.import.mockRejectedValueOnce(new Error('kind must be one of: stock, nuc'));
    view();
    await screen.findAllByTestId('inventory-row');
    await userEvent.click(screen.getByRole('button', { name: 'Import CSV' }));
    const dialog = screen.getByRole('dialog');
    await userEvent.upload(within(dialog).getByLabelText('CSV file'), new File(['"EntryName"\n"X1"\n'], 'Malk_Inventory.csv', { type: 'text/csv' }));
    await userEvent.selectOptions(within(dialog).getByLabelText('Client for the whole file'), 'c2');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Preview' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('kind must be one of');
    expect(api.import.mock.calls[0][0]).toMatchObject({ default_client_id: 'c2' });
  });
});

describe('InventoryView bulk edit', () => {
  it('selects several items and moves them all to one client in one request, then clears the selection', async () => {
    api.list.mockResolvedValue(list([item({ id: 'a', name: 'A1', client_id: null, client_name: null, customer_name: 'Acme Dntl' }), item({ id: 'b', name: 'B1', client_id: null, client_name: null, customer_name: 'Acme Dntl' }), item({ id: 'c', name: 'C1' })]));
    api.bulk.mockResolvedValue({ changed: 2, unchanged: 0, not_found: 0 });
    view();
    await screen.findAllByTestId('inventory-row');
    expect(screen.queryByTestId('bulk-bar')).toBeNull();
    await userEvent.click(screen.getByLabelText('Select A1'));
    await userEvent.click(screen.getByLabelText('Select B1'));
    expect(screen.getByTestId('bulk-bar')).toHaveTextContent('2 selected');
    await userEvent.click(screen.getByRole('button', { name: 'Edit selected' }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByRole('button', { name: 'Save 2 items' })).toBeDisabled();
    await userEvent.selectOptions(within(dialog).getByLabelText('Move to client'), 'c1');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save 2 items' }));
    await waitFor(() => expect(api.bulk).toHaveBeenCalledTimes(1));
    expect(api.bulk.mock.calls[0][0]).toEqual({ ids: ['a', 'b'], client_id: 'c1' });
    await waitFor(() => expect(screen.queryByTestId('bulk-bar')).toBeNull());
  });

  it('selects every item on the page with the header box, and can list the items not matched to a client', async () => {
    api.list.mockResolvedValue(list([item({ id: 'a', name: 'A1' }), item({ id: 'b', name: 'B1' })]));
    view();
    await screen.findAllByTestId('inventory-row');
    await userEvent.click(screen.getByLabelText('Select all on this page'));
    expect(screen.getByTestId('bulk-bar')).toHaveTextContent('2 selected');
    await userEvent.selectOptions(screen.getByLabelText('Client'), 'unmatched');
    await waitFor(() => expect(lastQuery().client).toBe('unmatched'));
    expect(screen.queryByTestId('bulk-bar')).toBeNull();
  });

  it('sends Live Oak own stock as move_to_own and shows the API message when the change is refused', async () => {
    api.bulk.mockRejectedValueOnce(new Error('Client not found'));
    view();
    await screen.findAllByTestId('inventory-row');
    await userEvent.click(screen.getByLabelText('Select Dell Pro Max 16'));
    await userEvent.click(screen.getByRole('button', { name: 'Edit selected' }));
    const dialog = screen.getByRole('dialog');
    await userEvent.selectOptions(within(dialog).getByLabelText('Move to client'), 'own');
    await userEvent.type(within(dialog).getByLabelText('Add a tag'), 'loaner');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save 1 items' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Client not found');
    expect(api.bulk.mock.calls[0][0]).toEqual({ ids: ['i1'], move_to_own: true, add_tags: ['loaner'] });
  });
});

describe('InventoryView device sync', () => {
  const result = (over: Record<string, unknown> = {}) => ({ dry_run: true, devices: 120, by_category: { Mac: 20, 'Windows computer': 100 }, matched: 80, matched_in_stock: 3, created: 40, refreshed: 0, no_serial: 2, ...over });

  it('previews what would be added, then adds the devices as checked out and refreshes the list', async () => {
    api.syncDevices.mockResolvedValueOnce(result()).mockResolvedValueOnce(result({ dry_run: false }));
    view();
    await screen.findAllByTestId('inventory-row');
    await userEvent.click(screen.getByRole('button', { name: 'Add devices from NinjaOne and Addigy' }));
    const preview = await screen.findByTestId('sync-preview');
    expect(preview).toHaveTextContent('120 devices reported (20 Mac, 100 Windows computer)');
    expect(preview).toHaveTextContent('80 already in the inventory, 3 of them marked checked in');
    expect(preview).toHaveTextContent('40 would be added as checked out');
    expect(api.syncDevices.mock.calls[0]).toEqual([true]);
    const before = api.list.mock.calls.length;
    await userEvent.click(screen.getByRole('button', { name: 'Add them' }));
    expect(await screen.findByTestId('sync-result')).toHaveTextContent('Added 40 as checked out');
    expect(api.syncDevices.mock.calls[1]).toEqual([false]);
    await waitFor(() => expect(api.list.mock.calls.length).toBeGreaterThan(before));
  });

  it('has nothing to add when every device is already there, and shows the API message when the device list cannot be read', async () => {
    api.syncDevices.mockResolvedValueOnce(result({ created: 0, matched: 120, matched_in_stock: 0, no_serial: 0 }));
    view();
    await screen.findAllByTestId('inventory-row');
    await userEvent.click(screen.getByRole('button', { name: 'Add devices from NinjaOne and Addigy' }));
    await screen.findByTestId('sync-preview');
    expect(screen.getByRole('button', { name: 'Add them' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    api.syncDevices.mockRejectedValueOnce(new Error('Forbidden'));
    await userEvent.click(screen.getByRole('button', { name: 'Add devices from NinjaOne and Addigy' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Forbidden');
  });
});
