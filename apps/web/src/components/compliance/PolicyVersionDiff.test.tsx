import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PolicyVersionDiff } from './PolicyVersionDiff';

describe('Policy version diff', () => {
  it('says how many lines were added and removed and shows each', () => {
    render(<PolicyVersionDiff version={2} before={'Keep logs\nReview yearly'} after={'Keep logs\nReview quarterly\nTell the owner'} />);
    expect(screen.getByText('Version 1 to version 2: 2 lines added, 1 removed.')).toBeInTheDocument();
    const diff = screen.getByTestId('policy-diff');
    expect(diff.textContent).toContain('- Review yearly');
    expect(diff.textContent).toContain('+ Review quarterly');
    expect(diff.textContent).toContain('+ Tell the owner');
  });
  it('says so when the text is the same', () => {
    render(<PolicyVersionDiff version={3} before="a" after="a" />);
    expect(screen.getByText('The text is the same.')).toBeInTheDocument();
  });
});
