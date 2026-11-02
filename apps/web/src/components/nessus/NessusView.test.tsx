import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SWRConfig } from 'swr';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));
vi.mock('@/lib/api', () => ({
  authApi: { currentUser: () => ({ tenant_id: 'own' }) },
  msspApi: { listChildren: async () => [{ id: 'c2', name: 'Birch Law' }, { id: 'c1', name: 'Acme Dental' }] },
}));

import { NessusView, hostsText } from './NessusView';

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
const scan = (over: Record<string, unknown> = {}) => ({ id: 's1', client_id: 'c1', client_name: 'Acme Dental', name: 'Monthly', description: null, notes: null, scan_type: 'lan', uploaded_by: 'hal', uploaded_at: '2026-11-02T10:00:00Z', hosts: 4, matched_hosts: 3, critical: 2, high: 1, medium: 0, low: 5, ...over });
const finding = (over: Record<string, unknown> = {}) => ({ host_name: 'ACME-PC01', host_ip: '10.0.0.5', host_os: null, device_id: 'd1', plugin_id: '1', name: 'Old TLS', severity: 'high', port: 443, protocol: 'tcp', service: 'www', cvss: 9.8, cves: ['CVE-2020-1'], exploit: true, synopsis: '', solution: 'Disable TLS 1.0', ...over });
let scans: unknown[];
let detail: Record<string, unknown>;
let uploads: { url: string; init: { method?: string; body?: unknown; headers?: Record<string, string> } }[];
let uploadStatus = 201;
let deleted: string[];

const view = () => (
  <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0, shouldRetryOnError: false }}>
    <NessusView />
  </SWRConfig>
);

beforeEach(() => {
  scans = [scan()];
  detail = { ...scan(), findings: [finding(), finding({ host_name: '10.0.0.77', device_id: null, name: 'Critical thing', severity: 'critical', exploit: false, cves: [] })], total_findings: 2, page: 1, pages: 1 };
  uploads = [];
  uploadStatus = 201;
  deleted = [];
  authFetch.mockReset();
  authFetch.mockImplementation(async (url: string, init?: { method?: string; body?: unknown; headers?: Record<string, string> }) => {
    if (init?.method === 'POST') {
      uploads.push({ url, init });
      return uploadStatus === 201 ? json(201, scan({ name: 'Uploaded', hosts: 2, critical: 1, high: 0 })) : json(uploadStatus, { detail: 'This is not a Nessus v2 export (.nessus).' });
    }
    if (init?.method === 'DELETE') {
      deleted.push(url);
      return new Response(null, { status: 204 });
    }
    if (url.startsWith('/api/v1/nessus/scans/')) return json(200, detail);
    if (url.startsWith('/api/v1/nessus/scans')) return json(200, scans);
    return json(404, {});
  });
});

describe('hostsText', () => {
  it('says how many scanned hosts are machines we know', () => {
    expect(hostsText({ hosts: 4, matched_hosts: 3 })).toBe('4 hosts: 3 in inventory, 1 not in inventory');
    expect(hostsText({ hosts: 1, matched_hosts: 1 })).toBe('1 host: 1 in inventory');
  });
});

describe('the scan list', () => {
  it('shows each scan with its client, type, host matching and severity counts', async () => {
    render(view());
    const row = await screen.findByTestId('scan-row');
    expect(within(row).getByText('Monthly')).toBeInTheDocument();
    expect(within(row).getByText('lan')).toBeInTheDocument();
    expect(within(row).getByText(/Acme Dental/)).toBeInTheDocument();
    expect(within(row).getByText(/4 hosts: 3 in inventory, 1 not in inventory/)).toBeInTheDocument();
    expect(within(row).getByText('2 critical')).toBeInTheDocument();
  });

  it('says plainly when nothing has been uploaded yet, and shows a refusal when the list cannot be read', async () => {
    scans = [];
    const first = render(view());
    expect(await screen.findByText(/No scans uploaded yet/)).toBeInTheDocument();
    first.unmount();
    authFetch.mockImplementation(async () => json(403, { detail: 'Permission denied: alerts:read' }));
    render(view());
    expect(await screen.findByRole('alert')).toHaveTextContent('Permission denied');
  });

  it('the client filter asks for that client only', async () => {
    render(view());
    await screen.findByTestId('scan-row');
    await userEvent.selectOptions(screen.getByLabelText('Show scans for'), 'Birch Law');
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/api/v1/nessus/scans?client_id=c2'));
  });
});

describe('uploading', () => {
  const file = (name = 'scan.nessus', size = 20) => new File([new Uint8Array(size)], name, { type: 'text/xml' });

  it('sends the file as the raw body with the chosen client, name and type, and says what it found', async () => {
    render(view());
    await screen.findByTestId('scan-row');
    await userEvent.selectOptions(await screen.findByLabelText('Client'), 'Birch Law');
    await userEvent.type(screen.getByLabelText('Scan name'), 'Q4 internal');
    await userEvent.selectOptions(screen.getByLabelText('Scan type'), 'wan');
    await userEvent.upload(screen.getByLabelText('Choose a .nessus file'), file());
    await waitFor(() => expect(uploads).toHaveLength(1));
    expect(uploads[0].url).toBe('/api/v1/nessus/scans?client_id=c2&name=Q4+internal&scan_type=wan');
    expect(uploads[0].init.body).toBeInstanceOf(File);
    expect(uploads[0].init.headers).toEqual({ 'Content-Type': 'application/octet-stream' });
    expect(await screen.findByText(/Added "Uploaded": 2 hosts, 1 critical and 0 high findings\./)).toBeInTheDocument();
  });

  it('shows the server\'s reason when the file is refused', async () => {
    uploadStatus = 422;
    render(view());
    await userEvent.upload(await screen.findByLabelText('Choose a .nessus file'), file());
    expect(await screen.findByRole('alert')).toHaveTextContent('This is not a Nessus v2 export');
  });

  it('refuses a file that is not .nessus, or too big, before sending anything', async () => {
    render(view());
    const input = await screen.findByLabelText('Choose a .nessus file');
    await userEvent.upload(input, file('notes.txt'), { applyAccept: false });
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose a .nessus file');
    const big = file('big.nessus', 10);
    Object.defineProperty(big, 'size', { value: 101 * 1024 * 1024 });
    await userEvent.upload(input, big);
    expect(await screen.findByRole('alert')).toHaveTextContent('larger than 100 MB');
    expect(uploads).toHaveLength(0);
  });
});

describe('a scan\'s findings', () => {
  it('shows each finding with its severity, exploit flag, CVEs, host matching and fix', async () => {
    render(view());
    await userEvent.click(await screen.findByRole('button', { name: 'View Monthly' }));
    const rows = await screen.findAllByTestId('finding-row');
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText('exploit')).toBeInTheDocument();
    expect(within(rows[0]).getByText('CVE-2020-1')).toBeInTheDocument();
    expect(within(rows[0]).getByText('in inventory')).toBeInTheDocument();
    expect(within(rows[0]).getByText('Disable TLS 1.0')).toBeInTheDocument();
    expect(within(rows[1]).getByText('not in inventory')).toBeInTheDocument();
    expect(within(rows[1]).queryByText('exploit')).not.toBeInTheDocument();
  });

  it('the filters ask the server for that severity and host', async () => {
    render(view());
    await userEvent.click(await screen.findByRole('button', { name: 'View Monthly' }));
    await screen.findAllByTestId('finding-row');
    await userEvent.selectOptions(screen.getByLabelText('Severity'), 'critical');
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/api/v1/nessus/scans/s1?page=1&page_size=25&severity=critical'));
    await userEvent.type(screen.getByLabelText('Host'), 'acme');
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/api/v1/nessus/scans/s1?page=1&page_size=25&severity=critical&host=acme'));
  });

  it('pages through a long scan', async () => {
    detail = { ...detail, total_findings: 60, pages: 3 };
    render(view());
    await userEvent.click(await screen.findByRole('button', { name: 'View Monthly' }));
    expect(await screen.findByTestId('page-info')).toHaveTextContent('60 findings · page 1 of 3');
    await userEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(authFetch).toHaveBeenCalledWith('/api/v1/nessus/scans/s1?page=2&page_size=25'));
  });
});

describe('deleting a scan', () => {
  it('asks first, names the scan, and deletes only after the person confirms', async () => {
    render(view());
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Monthly' }));
    expect(deleted).toHaveLength(0);
    expect(screen.getByText(/Monthly and all of its findings are removed/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(deleted).toEqual(['/api/v1/nessus/scans/s1']));
  });

  it('cancelling deletes nothing', async () => {
    render(view());
    await userEvent.click(await screen.findByRole('button', { name: 'Delete Monthly' }));
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(deleted).toHaveLength(0);
  });
});
