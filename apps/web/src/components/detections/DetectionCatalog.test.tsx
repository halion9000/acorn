import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.hoisted(() => vi.fn());
vi.mock('@/lib/auth-session', () => ({ authFetch }));

import { DetectionCatalog } from './DetectionCatalog';

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
const rule = { id: 'r1', name: 'Suspicious PowerShell', description: 'Encoded command line', author: 'Someone', level: 'high', tags: [], install_count: 3, rating: 0, rating_count: 0, status: 'approved', submitted_at: '2026-10-08T00:00:00Z' };

let installResponse: () => Promise<Response>;
let installedIds: string[] = [];

beforeEach(() => {
  authFetch.mockReset();
  installResponse = async () => json(200, { message: 'installed' });
  installedIds = [];
  authFetch.mockImplementation(async (url: string) => {
    if (url.includes('/installed/detections')) return json(200, { ids: installedIds });
    if (url.includes('/install')) return installResponse();
    return json(200, { items: [rule], total: 1, page: 1, page_size: 24 });
  });
});

async function renderAndFindInstall() {
  render(<DetectionCatalog />);
  await screen.findByText('Suspicious PowerShell');
  return screen.getByRole('button', { name: 'Install Rule' });
}

describe('a rule this workspace already installed', () => {
  it('opens as Installed, with nothing to click', async () => {
    installedIds = ['r1'];
    render(<DetectionCatalog />);
    await screen.findByText('Suspicious PowerShell');
    expect(await screen.findByRole('button', { name: /Installed/ })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Install Rule' })).not.toBeInTheDocument();
  });

  it('still offers Install when the installed list cannot be read', async () => {
    authFetch.mockImplementation(async (url: string) => {
      if (url.includes('/installed/detections')) return new Response('nope', { status: 500 });
      return json(200, { items: [rule], total: 1, page: 1, page_size: 24 });
    });
    render(<DetectionCatalog />);
    await screen.findByText('Suspicious PowerShell');
    expect(screen.getByRole('button', { name: 'Install Rule' })).toBeEnabled();
  });
});

// The Install button marked the rule "Installed" whenever the request merely COMPLETED: a 403 (no rules:write), a 400 or a 500 all showed a green "Installed".
describe('the Install button', () => {
  it('shows Installed, and nothing else, when the server confirms', async () => {
    const button = await renderAndFindInstall();
    await userEvent.setup().click(button);
    await waitFor(() => expect(screen.getByRole('button', { name: /Installed/ })).toBeDisabled());
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(authFetch).toHaveBeenCalledWith('/api/v1/community/detections/r1/install', { method: 'POST' });
  });

  it('shows the server\'s reason, and NOT Installed, when it is refused', async () => {
    installResponse = async () => json(403, { detail: 'Permission denied: rules:write' });
    await userEvent.setup().click(await renderAndFindInstall());
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not install: Permission denied: rules:write');
    expect(screen.queryByRole('button', { name: /Installed/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Install Rule' })).toBeEnabled(); // and it can be retried
  });

  it('says HTTP 500 when the server gives no explanation', async () => {
    installResponse = async () => new Response('boom', { status: 500 });
    await userEvent.setup().click(await renderAndFindInstall());
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not install: HTTP 500');
    expect(screen.queryByRole('button', { name: /Installed/ })).not.toBeInTheDocument();
  });

  it('says so when the network fails', async () => {
    installResponse = async () => { throw new Error('network down'); };
    await userEvent.setup().click(await renderAndFindInstall());
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not install: network down');
    expect(screen.queryByRole('button', { name: /Installed/ })).not.toBeInTheDocument();
  });

  it('shows Installed, without an error, when it was already installed here (409)', async () => {
    installResponse = async () => json(409, { detail: 'This detection is already installed' });
    await userEvent.setup().click(await renderAndFindInstall());
    await waitFor(() => expect(screen.getByRole('button', { name: /Installed/ })).toBeDisabled());
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('clears the error when a retry works', async () => {
    installResponse = async () => json(500, { detail: 'temporary' });
    const user = userEvent.setup();
    await user.click(await renderAndFindInstall());
    await screen.findByRole('alert');
    installResponse = async () => json(200, {});
    await user.click(screen.getByRole('button', { name: 'Install Rule' }));
    await waitFor(() => expect(screen.getByRole('button', { name: /Installed/ })).toBeInTheDocument());
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

describe('an empty catalog', () => {
  it('says what the catalog is and links to where the running rules and the vendor detections are', async () => {
    authFetch.mockImplementation(async () => json(200, { items: [], total: 0, page: 1, page_size: 24 }));
    render(<DetectionCatalog />);
    expect(await screen.findByText('No detection rules found.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Detection Rules' })).toHaveAttribute('href', '/detection');
    expect(screen.getByRole('link', { name: 'Vendor detections' })).toHaveAttribute('href', '/detection/vendor-detections');
    expect(document.body.textContent).toContain('published to share');
  });
});

describe('the licence link', () => {
  it('links to the licence of an imported rule, and only over https', async () => {
    authFetch.mockImplementation(async () => json(200, { items: [{ ...rule, license_url: 'https://github.com/SigmaHQ/Detection-Rule-License' }, { ...rule, id: 'r2', name: 'Other rule', license_url: 'javascript:alert(1)' }], total: 2, page: 1, page_size: 24 }));
    render(<DetectionCatalog />);
    await screen.findByText('Other rule');
    const links = screen.getAllByRole('link', { name: 'Licence' });
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute('href', 'https://github.com/SigmaHQ/Detection-Rule-License');
  });
});
