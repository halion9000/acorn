import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { MetricPicker, applyToMatches, filterOptions, pickerSummary } from './MetricPicker';

const OPTIONS = [
  { value: 'a', label: 'Exchange Administrator', hint: '(321)' },
  { value: 'b', label: 'Global Reader', hint: '(235)' },
  { value: 'c', label: 'Teams Administrator', hint: '(227)' },
];

describe('the picker helpers', () => {
  it('filters by every word in the label or the note, any letter case, and keeps all for no text', () => {
    expect(filterOptions(OPTIONS, 'admin').map((o) => o.value)).toEqual(['a', 'c']);
    expect(filterOptions(OPTIONS, 'TEAMS admin').map((o) => o.value)).toEqual(['c']);
    expect(filterOptions(OPTIONS, '235').map((o) => o.value)).toEqual(['b']);
    expect(filterOptions(OPTIONS, '  ')).toEqual(OPTIONS);
    expect(filterOptions(OPTIONS, 'zzz')).toEqual([]);
  });
  it('says how many are shown in words', () => {
    expect([pickerSummary(3, 3, 'roles'), pickerSummary(1, 3, 'roles'), pickerSummary(0, 3, 'roles'), pickerSummary(0, 0, 'roles')]).toEqual(['All 3 roles', '1 of 3 roles', 'No roles shown', 'No roles']);
  });
  it('Select all and Clear touch only the matches, so a search can pick a whole family at once', () => {
    const matches = OPTIONS.filter((o) => /admin/i.test(o.label));
    expect(applyToMatches(['b'], matches, true).sort()).toEqual(['a', 'b', 'c']);
    expect(applyToMatches(['a', 'b', 'c'], matches, false)).toEqual(['b']);
    expect(applyToMatches([], OPTIONS, true).sort()).toEqual(['a', 'b', 'c']);
  });
});

function Harness({ start = ['a', 'b', 'c'] }: { start?: string[] }) {
  const [sel, setSel] = useState(start);
  return (
    <>
      <MetricPicker noun="roles" options={OPTIONS} selected={sel} onChange={setSel} />
      <output data-testid="chosen">{[...sel].sort().join(',')}</output>
    </>
  );
}

describe('the picker', () => {
  it('shows only a button until it is opened, then a searchable list with the choices ticked', async () => {
    render(<Harness />);
    expect(screen.getByRole('button', { name: /All 3 roles/ })).toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: /All 3 roles/ }));
    expect(screen.getAllByRole('checkbox')).toHaveLength(3);
    await userEvent.click(screen.getByLabelText(/Global Reader/));
    expect(screen.getByTestId('chosen')).toHaveTextContent('a,c');
    expect(screen.getByRole('button', { name: /2 of 3 roles/ })).toBeInTheDocument();
  });

  it('narrows the list as you type, and Clear matching unticks just those', async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole('button', { name: /All 3 roles/ }));
    await userEvent.type(screen.getByLabelText('Search roles'), 'admin');
    expect(screen.getAllByRole('checkbox')).toHaveLength(2);
    expect(screen.getByText('2 shown')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Clear matching' }));
    expect(screen.getByTestId('chosen')).toHaveTextContent('b');
    await userEvent.click(screen.getByRole('button', { name: 'Select all matching' }));
    expect(screen.getByTestId('chosen')).toHaveTextContent('a,b,c');
  });

  it('says nothing matches, and closes on Escape and on a click outside', async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole('button', { name: /All 3 roles/ }));
    await userEvent.type(screen.getByLabelText('Search roles'), 'qqq');
    expect(screen.getByText('Nothing matches.')).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: /All 3 roles/ }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
