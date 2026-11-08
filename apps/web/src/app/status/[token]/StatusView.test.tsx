import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { StatusView } from './StatusView';
import type { ClientStatusPage } from '../../../lib/client-status';

const copy = { title: 'Your security status', intro: 'intro text', devices: 'Computers with endpoint protection', people: 'People protected by a second sign-in step', alerts_open: 'Security alerts open now', alerts_handled: 'of those, already being worked on by your provider', tools: 'Protections in place', footer: 'Questions? Contact your IT provider.' };
const page = (over: Partial<ClientStatusPage> = {}): ClientStatusPage => ({
  client_name: 'Acme',
  generated_at: '2026-11-08T12:00:00Z',
  devices: { total: 50, protected: 45, percent: 90 },
  people: { total: 80, protected: 70, percent: 88 },
  alerts: { open: 12, being_worked_on: 7 },
  tools: ['Managed endpoint detection (Huntress)'],
  copy,
  ...over,
});

describe('StatusView', () => {
  it('draws the numbers and wording the API sent, and nothing else', () => {
    render(<StatusView page={page()} />);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Your security status');
    expect(screen.getByTestId('status-devices')).toHaveTextContent('90%');
    expect(screen.getByTestId('status-devices')).toHaveTextContent('45 of 50');
    expect(screen.getByTestId('status-people')).toHaveTextContent('88%');
    expect(screen.getByTestId('status-alerts')).toHaveTextContent('12');
    expect(screen.getByTestId('status-alerts')).toHaveTextContent('7 of those, already being worked on by your provider');
    expect(screen.getByTestId('status-tools')).toHaveTextContent('Managed endpoint detection (Huntress)');
  });

  it('says "Not available yet" instead of guessing, hides an empty tool list and the handled line at zero alerts', () => {
    render(<StatusView page={page({ people: null, devices: { total: 0, protected: 0, percent: null }, alerts: { open: 0, being_worked_on: 0 }, tools: [] })} />);
    expect(screen.getByTestId('status-people')).toHaveTextContent('Not available yet');
    expect(screen.getByTestId('status-devices')).toHaveTextContent('Not available yet');
    expect(screen.queryByTestId('status-tools')).toBeNull();
    expect(screen.getByTestId('status-alerts')).not.toHaveTextContent('already being worked on');
  });
});
