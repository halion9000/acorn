import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { RevisionsView } from './RevisionsView';
import { REVISIONS, APP_VERSION } from '@/lib/revisions';

describe('Revisions', () => {
  it('the current version is the newest revision, and every revision has a unique number and a date', () => {
    expect(APP_VERSION).toBe(REVISIONS[0].version);
    expect(new Set(REVISIONS.map((r) => r.version)).size).toBe(REVISIONS.length);
    expect(REVISIONS.every((r) => /^1\.\d+$/.test(r.version) && /^\d{4}-\d{2}-\d{2}$/.test(r.weekOf))).toBe(true);
    const dates = REVISIONS.map((r) => r.weekOf);
    expect([...dates].sort().reverse()).toEqual(dates);
  });

  it('the page lists every revision and marks the newest as current', () => {
    render(<RevisionsView />);
    expect(screen.getAllByTestId('revision')).toHaveLength(REVISIONS.length);
    expect(screen.getByText('Current')).toBeInTheDocument();
    expect(screen.getAllByText(`v${APP_VERSION}`).length).toBeGreaterThan(0);
  });
});
