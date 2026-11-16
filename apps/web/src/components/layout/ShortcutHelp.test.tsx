import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ShortcutHelp, isHelpKey } from './ShortcutHelp';

const key = (over: Partial<Parameters<typeof isHelpKey>[0]> = {}) => ({ key: '?', ctrlKey: false, metaKey: false, altKey: false, target: { tagName: 'BODY' }, ...over });

describe('isHelpKey', () => {
  it('accepts a bare question mark away from a text box', () => {
    expect(isHelpKey(key())).toBe(true);
  });
  it('ignores other keys, modified keys and text boxes', () => {
    expect(isHelpKey(key({ key: 'a' }))).toBe(false);
    expect(isHelpKey(key({ ctrlKey: true }))).toBe(false);
    expect(isHelpKey(key({ metaKey: true }))).toBe(false);
    expect(isHelpKey(key({ target: { tagName: 'INPUT' } }))).toBe(false);
    expect(isHelpKey(key({ target: { tagName: 'textarea' } }))).toBe(false);
    expect(isHelpKey(key({ target: { tagName: 'SELECT' } }))).toBe(false);
    expect(isHelpKey(key({ target: { tagName: 'DIV', isContentEditable: true } }))).toBe(false);
  });
});

describe('ShortcutHelp', () => {
  it('opens on ? and closes on ? again, Escape or the Close button', async () => {
    render(<ShortcutHelp />);
    expect(screen.queryByRole('dialog')).toBeNull();
    await userEvent.keyboard('?');
    expect(screen.getByRole('dialog', { name: 'Keyboard shortcuts' })).toHaveTextContent('Open the command palette');
    await userEvent.keyboard('?');
    expect(screen.queryByRole('dialog')).toBeNull();
    await userEvent.keyboard('?');
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
    await userEvent.keyboard('?');
    await userEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('does not open while typing a question mark into a box', async () => {
    render(
      <div>
        <input aria-label="Box" />
        <ShortcutHelp />
      </div>,
    );
    await userEvent.type(screen.getByLabelText('Box'), 'why?');
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
