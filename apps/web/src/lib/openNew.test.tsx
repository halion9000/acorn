import { afterEach, describe, expect, it } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import { useState } from 'react';

import { NEW_EVENTS, useOpenOnNew, wantsNew, withoutNew } from './openNew';

function Page({ kind }: { kind: 'case' | 'alert' }) {
  const [open, setOpen] = useState(false);
  useOpenOnNew(kind, () => setOpen(true));
  return <p data-testid="state">{open ? 'open' : 'closed'}</p>;
}

afterEach(() => window.history.replaceState(null, '', '/'));

describe('wantsNew and withoutNew', () => {
  it('asks only for exactly ?new=1', () => {
    expect(wantsNew('?new=1')).toBe(true);
    expect(wantsNew('?client=abc&new=1')).toBe(true);
    expect(wantsNew('?new=0')).toBe(false);
    expect(wantsNew('?newish=1')).toBe(false);
    expect(wantsNew('')).toBe(false);
  });
  it('takes only the new part out of the address', () => {
    expect(withoutNew('/cases', '?new=1')).toBe('/cases');
    expect(withoutNew('/cases', '?client=abc&new=1&status=open')).toBe('/cases?client=abc&status=open');
    expect(withoutNew('/cases', '')).toBe('/cases');
  });
});

describe('useOpenOnNew', () => {
  it('opens the dialog when the page is reached with ?new=1 and cleans the address, keeping the rest', () => {
    window.history.replaceState(null, '', '/cases?client=abc&new=1');
    render(<Page kind="case" />);
    expect(screen.getByTestId('state')).toHaveTextContent('open');
    expect(window.location.pathname + window.location.search).toBe('/cases?client=abc');
  });

  it('stays closed on a plain visit, then opens when the palette asks, and only for its own kind', () => {
    window.history.replaceState(null, '', '/cases');
    render(<Page kind="case" />);
    expect(screen.getByTestId('state')).toHaveTextContent('closed');
    act(() => void window.dispatchEvent(new Event(NEW_EVENTS.alert)));
    expect(screen.getByTestId('state')).toHaveTextContent('closed');
    act(() => void window.dispatchEvent(new Event(NEW_EVENTS.case)));
    expect(screen.getByTestId('state')).toHaveTextContent('open');
  });

  it('stops listening when the page is left', () => {
    const { unmount } = render(<Page kind="alert" />);
    unmount();
    expect(() => window.dispatchEvent(new Event(NEW_EVENTS.alert))).not.toThrow();
  });
});
