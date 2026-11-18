import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

// Mock Next.js routing primitives. The Sidebar reads `usePathname` to decide
// which item is active and uses `<Link>` for navigation; for a smoke test we
// just need both to behave as plain functions/elements.
vi.mock('next/navigation', () => ({
  usePathname: () => '/dashboard',
}));

vi.mock('next/link', () => ({
  default: ({
    children,
    href,
    className,
  }: {
    children: React.ReactNode;
    href: string;
    className?: string;
  }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));

import { Sidebar } from './Sidebar';
import { APP_VERSION } from '@/lib/revisions';

describe('Sidebar', () => {
  it('renders the A.C.O.R.N mark and the major nav sections', () => {
    render(<Sidebar />);

    // Brand
    expect(screen.getByText('A.C.')).toBeInTheDocument();
    expect(screen.getByText('O.R.N')).toBeInTheDocument();

    // Section headings — Dashboard sits in an unlabelled lead section,
    // everything else is grouped under one of these four titles.
    expect(screen.getByText('Threat Operations')).toBeInTheDocument();
    expect(screen.getByText('Intelligence')).toBeInTheDocument();
    expect(screen.getByText('Automation')).toBeInTheDocument();
    expect(screen.getByText('Platform')).toBeInTheDocument();
  });

  it('exposes the compliance entry point, and no longer the Marketplace or the Detection Catalog', () => {
    render(<Sidebar />);

    expect(screen.queryByRole('link', { name: /marketplace/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /detection catalog/i })).not.toBeInTheDocument();

    const dashboard = screen.getAllByRole('link').find((a) => a.getAttribute('href') === '/compliance');
    expect(dashboard).toHaveTextContent('Overview');
  });

  it('has a Compliance section of its own, apart from vCIO, with the pages that are built', () => {
    const { container } = render(<Sidebar />);
    expect(screen.getByText('Compliance')).toBeInTheDocument();
    const section = screen.getByText('Compliance').closest('div')!;
    const links = [...section.querySelectorAll('a')].map((a) => [a.textContent, a.getAttribute('href')]);
    expect(links).toEqual([
      ['Overview', '/compliance'],
      ['Frameworks', '/compliance/frameworks'],
      ['Controls', '/compliance/controls'],
      ['Tests', '/compliance/tests'],
      ['Policies', '/compliance/policies'],
      ['Risk Management', '/compliance/risk-register'],
      ['Vendors', '/compliance/vendors'],
      ['Access Reviews', '/compliance/access-reviews'],
      ['People', '/compliance/people'],
      ['Questionnaires', '/compliance/questionnaires'],
      ['Audits', '/compliance/audits'],
      ['Calendar', '/compliance/calendar'],
      ['Trust Center', '/compliance/trust-center'],
      ['Asset Inventory', '/inventory'],
    ]);
    const vcio = screen.getByText('vCIO').closest('div')!;
    expect([...vcio.querySelectorAll('a')].map((a) => a.getAttribute('href'))).not.toContain('/compliance');
    const hrefs = [...container.querySelectorAll('a')].map((a) => a.getAttribute('href'));
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  it('has a Client Security section with the client posture, Multi-Factor and sign-in scores pages, and cleanup and platform health live under Settings instead', () => {
    const { container } = render(<Sidebar />);
    expect(screen.getByText('Client Security')).toBeInTheDocument();
    const hrefs = [...container.querySelectorAll('a')].map((a) => a.getAttribute('href'));
    for (const h of ['/settings/client-posture', '/settings/mfa', '/settings/signin-scores']) expect(hrefs).toContain(h);
    for (const h of ['/settings/client-cleanup', '/settings/platform-health']) expect(hrefs).not.toContain(h);
  });

  it('shows the current version in the footer as a link to the revisions page, and no license line', () => {
    render(<Sidebar />);

    const version = screen.getByRole('link', { name: new RegExp(`^v${APP_VERSION.replace('.', '\\.')}$`) });
    expect(version).toHaveAttribute('href', '/settings/revisions');
    expect(screen.queryByText(/MIT License/i)).toBeNull();
  });
});

describe('Sidebar wordmark', () => {
  it('is one colour all the way through, with the full name underneath', () => {
    render(<Sidebar />);
    const a = screen.getByText('A.C.');
    const b = screen.getByText('O.R.N');
    const colour = (el: HTMLElement) => (el.className.match(/text-[a-z]+-\d+/) ?? [''])[0];
    expect(colour(a)).toBe(colour(b));
    expect(colour(a)).not.toBe('');
    expect(screen.getByText('Automated Cyber Operations & Response Network')).toBeInTheDocument();
    expect(screen.queryByText('open-source')).toBeNull();
  });
});

describe('Sidebar: Response & Defense and Automation', () => {
  const linksOf = (title: string) => {
    const section = screen.getByText(title, { selector: 'h3, h2, p, span, div' }).closest('div')!;
    return [...section.querySelectorAll('a')].map((a) => [a.textContent, a.getAttribute('href')]);
  };

  it('keeps the old Automation pages under Response & Defense', () => {
    render(<Sidebar />);
    expect(linksOf('Response & Defense')).toEqual([
      ['Playbooks', '/playbooks'],
      ['File Integrity (FIM)', '/fim'],
      ['Honeytokens', '/honeytokens'],
      ['Purple Team', '/purple-team'],
    ]);
  });

  it('has a new Automation section with the auto tickets, the auto scripts and HubSpot', () => {
    render(<Sidebar />);
    expect(linksOf('Automation')).toEqual([
      ['Auto Tickets', '/automation/tickets'],
      ['Auto Scripts', '/automation/scripts'],
      ['HubSpot', '/automation/hubspot'],
    ]);
  });
});
