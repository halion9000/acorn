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

    const compliance = screen.getByRole('link', { name: /compliance/i });
    expect(compliance).toHaveAttribute('href', '/compliance');
  });

  it('has a Client Security section with the client posture, Multi-Factor and sign-in scores pages, and cleanup and platform health live under Settings instead', () => {
    const { container } = render(<Sidebar />);
    expect(screen.getByText('Client Security')).toBeInTheDocument();
    const hrefs = [...container.querySelectorAll('a')].map((a) => a.getAttribute('href'));
    for (const h of ['/settings/client-posture', '/settings/mfa', '/settings/signin-scores']) expect(hrefs).toContain(h);
    for (const h of ['/settings/client-cleanup', '/settings/platform-health']) expect(hrefs).not.toContain(h);
  });

  it('renders the MIT license attribution in the footer', () => {
    render(<Sidebar />);

    const license = screen.getByRole('link', { name: /MIT License/i });
    expect(license).toHaveAttribute('href', 'https://github.com/beenuar/AiSOC');
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
