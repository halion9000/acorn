import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';

import { ToolChecks } from './ToolChecks';

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
        ]}
      />,
    );
    const box = screen.getByTestId('liongard-checks');
    expect(within(box).getByText('Liongard')).toBeInTheDocument();
    expect(within(screen.getByTestId('check-liongard_disk_encryption')).getByText('Disk encryption (BitLocker)')).toBeInTheDocument();
    expect(within(screen.getByTestId('check-liongard_disk_encryption')).getByText('Problem')).toBeInTheDocument();
    expect(within(screen.getByTestId('check-liongard_edr_coverage')).getByText('EDR coverage')).toBeInTheDocument();
    expect(within(screen.getByTestId('check-liongard_stale_licensed_users')).getByText('Needs attention')).toBeInTheDocument();
  });
});
