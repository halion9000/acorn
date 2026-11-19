import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import { Doughnut, doughnutBackground } from './Doughnut';

afterEach(() => cleanup());

describe('the doughnut', () => {
  it('splits the ring by share, leaves out an empty slice, and is grey with nothing', () => {
    expect(doughnutBackground([{ label: 'a', value: 3, color: '#1' }, { label: 'b', value: 0, color: '#2' }, { label: 'c', value: 1, color: '#3' }])).toBe('conic-gradient(#1 0.00% 75.00%, #3 75.00% 100.00%)');
    expect(doughnutBackground([{ label: 'a', value: 0, color: '#1' }])).toBe('conic-gradient(#4b5563 0 100%)');
  });

  it('names each slice with its count and share and the total in the middle', () => {
    render(<Doughnut slices={[{ label: 'Positive', value: 3, color: '#1' }, { label: 'Negative', value: 1, color: '#2' }]} />);
    const d = screen.getByTestId('doughnut');
    expect(within(d).getByText('3 (75%)')).toBeInTheDocument();
    expect(within(d).getByText('1 (25%)')).toBeInTheDocument();
    expect(within(d).getByText('4')).toBeInTheDocument();
  });
});
