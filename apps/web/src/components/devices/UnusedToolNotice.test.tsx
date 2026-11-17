import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { UnusedToolNotice } from './UnusedToolNotice';

const summary = { total: 8, kinds: { computer: 8 }, reporting_tools: ['ninjaone'], not_in_huntress: 8, not_in_threatmate: 2 };

describe('the unused tool notice on Devices', () => {
  it('names the tool no computer has and links to the posture page for that client', () => {
    render(<UnusedToolNotice clientId="c 1" summary={summary} excluded={[]} />);
    const note = screen.getByTestId('unused-tool-notice');
    expect(note).toHaveTextContent("none of this client's 8 computers has it");
    expect(screen.getByRole('link', { name: 'Tools this client does not use' })).toHaveAttribute('href', '/settings/client-posture?client=c%201');
  });
  it('shows nothing without a chosen client, for a tool already marked not used, or when every tool has some computers', () => {
    const { container, rerender } = render(<UnusedToolNotice clientId="" summary={summary} excluded={[]} />);
    expect(container.textContent).toBe('');
    rerender(<UnusedToolNotice clientId="c1" summary={summary} excluded={['huntress']} />);
    expect(container.textContent).toBe('');
    rerender(<UnusedToolNotice clientId="c1" summary={{ ...summary, not_in_huntress: 3 }} excluded={[]} />);
    expect(container.textContent).toBe('');
  });
});
