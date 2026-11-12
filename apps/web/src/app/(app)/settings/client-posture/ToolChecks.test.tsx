import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';

import { ToolChecks, targetWords } from './ToolChecks';

describe('ToolChecks', () => {
  it('shows each check with a plain verdict and what ThreatMate saw', () => {
    render(
      <ToolChecks
        tool="threatmate"
        label="ThreatMate"
        refreshedAt="2026-10-24T03:00:00Z"
        checks={[
          { key: 'threatmate_security_score', status: 'met', evidence: 'ThreatMate security score 97.9 out of 100' },
          { key: 'threatmate_patching', status: 'not_met', evidence: '1 of 3 devices are patch-compliant in ThreatMate (33.3%)' },
          { key: 'threatmate_end_of_life', status: 'partly', evidence: 'ThreatMate: 1 application past end of life' },
        ]}
      />,
    );
    expect(within(screen.getByTestId('check-threatmate_security_score')).getByText('Good')).toBeInTheDocument();
    const patching = screen.getByTestId('check-threatmate_patching');
    expect(within(patching).getByText('Problem')).toBeInTheDocument();
    expect(within(patching).getByText('Patching')).toBeInTheDocument();
    expect(within(patching).getByText(/1 of 3 devices/)).toBeInTheDocument();
    expect(within(screen.getByTestId('check-threatmate_end_of_life')).getByText('Needs attention')).toBeInTheDocument();
  });

  it('shows nothing for a client with no ThreatMate checks', () => {
    const { container } = render(<ToolChecks tool="threatmate" label="ThreatMate" checks={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('names the Liongard checks in plain words under their own heading', () => {
    render(
      <ToolChecks
        tool="liongard"
        label="Liongard"
        checks={[
          { key: 'liongard_disk_encryption', status: 'not_met', evidence: 'Liongard: 0 of 2 workstations have every fixed drive fully encrypted with BitLocker' },
          { key: 'liongard_edr_coverage', status: 'met', evidence: 'Liongard: 2 of 2 Windows machines list an EDR agent (100%)' },
          { key: 'liongard_stale_licensed_users', status: 'partly', evidence: 'Liongard: 3 stale Microsoft 365 users still hold a licence' },
          { key: 'liongard_iis_certificates', status: 'not_met', evidence: "Liongard: of 2 IIS certificates on the client's servers, 1 expired: mail.acme.com (12 days ago)" },
        ]}
      />,
    );
    const box = screen.getByTestId('liongard-checks');
    expect(within(box).getByText('Liongard')).toBeInTheDocument();
    expect(within(screen.getByTestId('check-liongard_disk_encryption')).getByText('Disk encryption (BitLocker)')).toBeInTheDocument();
    expect(within(screen.getByTestId('check-liongard_disk_encryption')).getByText('Problem')).toBeInTheDocument();
    expect(within(screen.getByTestId('check-liongard_edr_coverage')).getByText('EDR coverage')).toBeInTheDocument();
    expect(within(screen.getByTestId('check-liongard_stale_licensed_users')).getByText('Needs attention')).toBeInTheDocument();
    expect(within(screen.getByTestId('check-liongard_iis_certificates')).getByText('Web server certificates (IIS)')).toBeInTheDocument();
  });

  it('names the hardening and cyber insurance checks in plain words', () => {
    render(
      <ToolChecks
        tool="threatmate"
        label="ThreatMate"
        checks={[
          { key: 'threatmate_hardening', status: 'not_met', evidence: 'ThreatMate endpoint hardening: 45% of checks pass on the 12 of 62 devices assessed' },
          { key: 'threatmate_cyber_insurance', status: 'partly', evidence: "ThreatMate's Cyber Insurance Baseline: 60 of 100 checks pass (60%)" },
          { key: 'threatmate_external_exposure', status: 'not_met', evidence: 'ThreatMate scans 1 public address and 2 domains from outside and finds 1 high issue' },
          { key: 'threatmate_dmarc', status: 'partly', evidence: "ThreatMate finds DMARC issues on 2 and SPF issues on 1 of the client's 3 domains" },
        ]}
      />,
    );
    expect(within(screen.getByTestId('check-threatmate_hardening')).getByText('Endpoint hardening')).toBeInTheDocument();
    expect(within(screen.getByTestId('check-threatmate_cyber_insurance')).getByText('Cyber insurance baseline')).toBeInTheDocument();
    expect(within(screen.getByTestId('check-threatmate_external_exposure')).getByText('External exposure')).toBeInTheDocument();
    expect(within(screen.getByTestId('check-threatmate_dmarc')).getByText('DMARC and SPF')).toBeInTheDocument();
  });

  it('names the IT Glue expiry checks in plain words under their own heading', () => {
    render(
      <ToolChecks
        tool="itglue"
        label="IT Glue"
        checks={[
          { key: 'itglue_domain_expiry', status: 'not_met', evidence: 'IT Glue documents 2 domains; 1 expired: old.com (2026-10-14)' },
          { key: 'itglue_certificate_expiry', status: 'partly', evidence: 'IT Glue documents 1 certificate; 1 expire within 30 days: mail (2026-11-02)' },
        ]}
      />,
    );
    expect(within(screen.getByTestId('itglue-checks')).getByText('IT Glue')).toBeInTheDocument();
    expect(within(screen.getByTestId('check-itglue_domain_expiry')).getByText('Domain names')).toBeInTheDocument();
    expect(within(screen.getByTestId('check-itglue_domain_expiry')).getByText('Problem')).toBeInTheDocument();
    expect(within(screen.getByTestId('check-itglue_certificate_expiry')).getByText('SSL certificates')).toBeInTheDocument();
  });

  it('names the two Google super administrator count checks in plain words', async () => {
    render(
      <ToolChecks
        tool="threatmate-google"
        label="Google Workspace"
        checks={[
          { key: 'threatmate_google_super_admin_min', status: 'not_met', evidence: '1 Google super administrator; the template wants at least 2' },
          { key: 'threatmate_google_super_admin_max', status: 'met', evidence: '1 Google super administrator; the template wants no more than 4.' },
        ]}
      />,
    );
    expect(within(screen.getByTestId('check-threatmate_google_super_admin_min')).getByText('At least two Google super administrators')).toBeInTheDocument();
    expect(within(screen.getByTestId('check-threatmate_google_super_admin_max')).getByText('No more than four Google super administrators')).toBeInTheDocument();
    const { CHECK_HELP } = await import('./checkHelp');
    expect(CHECK_HELP.threatmate_google_super_admin_min.fix).toMatch(/second trusted person/);
    expect(CHECK_HELP.threatmate_google_super_admin_max.fix).toMatch(/two to four/);
  });

  it('names the servers-only update check in plain words, apart from the all-machines one', async () => {
    render(
      <ToolChecks
        tool="ninjaone"
        label="NinjaOne"
        checks={[
          { key: 'ninjaone_patching', status: 'partly', evidence: '1 of 22 Windows machines behind' },
          { key: 'ninjaone_server_patching', status: 'not_met', evidence: '1 of 2 Windows servers behind' },
        ]}
      />,
    );
    expect(within(screen.getByTestId('check-ninjaone_patching')).getByText('Windows updates')).toBeInTheDocument();
    expect(within(screen.getByTestId('check-ninjaone_server_patching')).getByText('Windows updates on servers')).toBeInTheDocument();
    const { CHECK_HELP } = await import('./checkHelp');
    expect(CHECK_HELP.ninjaone_server_patching.fix).toMatch(/servers listed/);
  });
});

describe('the time-to-fix target', () => {
  it('says the target in words and marks a check that is past it', () => {
    expect([4, 24, 120, 336].map(targetWords)).toEqual(['4 hours', '1 day', '5 days', '14 days']);
    render(
      <ToolChecks
        tool="ninjaone"
        label="NinjaOne"
        checks={[
          { key: 'ninjaone_disk_health', status: 'not_met', evidence: '1 device has a failing disk', since: '2026-11-01T00:00:00Z', target_hours: 24, over_target: true },
          { key: 'ninjaone_antivirus', status: 'not_met', evidence: '2 machines have no antivirus', since: '2026-11-10T00:00:00Z', target_hours: 336, over_target: false },
          { key: 'ninjaone_patching', status: 'partly', evidence: 'x' },
        ]}
      />,
    );
    expect(screen.getByTestId('target-ninjaone_disk_health')).toHaveTextContent('past its 1 day target');
    expect(screen.getByTestId('target-ninjaone_antivirus')).toHaveTextContent('fix within 14 days');
    expect(screen.queryByTestId('target-ninjaone_patching')).toBeNull();
  });
});

