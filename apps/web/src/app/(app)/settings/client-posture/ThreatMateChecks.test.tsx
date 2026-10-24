import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';

import { ThreatMateChecks } from './ThreatMateChecks';

describe('ThreatMateChecks', () => {
  it('shows each check with a plain verdict and what ThreatMate saw', () => {
    render(
      <ThreatMateChecks
        refreshedAt="2026-10-24T03:00:00Z"
        checks={[
          { key: 'threatmate_security_score', status: 'met', evidence: 'ThreatMate security score 97.9 out of 100' },
          { key: 'threatmate_patching', status: 'not_met', evidence: '1 of 3 devices are patch-compliant in ThreatMate (33.3%)' },
          { key: 'threatmate_end_of_life', status: 'partly', evidence: 'ThreatMate: 1 application past end of life' },
        ]}
      />,
    );
    expect(within(screen.getByTestId('tm-threatmate_security_score')).getByText('Good')).toBeInTheDocument();
    const patching = screen.getByTestId('tm-threatmate_patching');
    expect(within(patching).getByText('Problem')).toBeInTheDocument();
    expect(within(patching).getByText('Patching')).toBeInTheDocument();
    expect(within(patching).getByText(/1 of 3 devices/)).toBeInTheDocument();
    expect(within(screen.getByTestId('tm-threatmate_end_of_life')).getByText('Needs attention')).toBeInTheDocument();
  });

  it('shows nothing for a client with no ThreatMate checks', () => {
    const { container } = render(<ThreatMateChecks checks={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
