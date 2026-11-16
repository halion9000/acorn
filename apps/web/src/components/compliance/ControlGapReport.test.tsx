import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ControlRowT } from '@/lib/api';
import { ControlGapReport } from './ControlGapReport';

const saveText = vi.fn();
vi.mock('@/lib/saveFile', () => ({ saveText: (...a: unknown[]) => saveText(...a) }));

const row = (id: string, accepted: number, owner: string | null): ControlRowT => ({ framework: 'SOC2', control_id: id, title: `T ${id}`, group: 'G', state: 'not_tested', accepted, pending: 0, rejected: 0, newest_evidence: null, age_days: null, link: '', owner });

describe('Gap report on the Controls page', () => {
  beforeEach(() => saveText.mockClear());
  it('says how many controls have neither evidence nor an owner and downloads exactly those', () => {
    render(<ControlGapReport rows={[row('CC1', 0, null), row('CC2', 2, 'Ann'), row('CC3', 0, null)]} />);
    expect(screen.getByText(/2 controls with no evidence and no owner/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Download the controls with neither/ }));
    const [name, csv] = saveText.mock.calls[0] as [string, string];
    expect(name).toBe('control-gaps.csv');
    expect(csv.split('\r\n').slice(1, 3)).toEqual(['SOC2,CC1,T CC1,G,not_tested', 'SOC2,CC3,T CC3,G,not_tested']);
  });
  it('has no download when nothing is missing both, and renders nothing for an empty list', () => {
    const { container, rerender } = render(<ControlGapReport rows={[row('CC1', 1, null)]} />);
    expect(screen.getByText(/every listed control has evidence or an owner/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Download/ })).toBeNull();
    rerender(<ControlGapReport rows={[]} />);
    expect(container.textContent).toBe('');
  });
});
