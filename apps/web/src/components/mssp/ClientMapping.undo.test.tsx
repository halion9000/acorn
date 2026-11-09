import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { MappedToast } from './ClientMapping';

describe('MappedToast', () => {
  it('says what was mapped and takes it back when Undo is pressed', async () => {
    const onUndo = vi.fn();
    render(<MappedToast message="Mapped Acme Dental" onUndo={onUndo} />);
    expect(screen.getByTestId('mapped-toast')).toHaveTextContent('Mapped Acme Dental');
    await userEvent.click(screen.getByRole('button', { name: 'Undo' }));
    expect(onUndo).toHaveBeenCalledTimes(1);
  });
});
