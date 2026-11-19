import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';

import { PushToggle, keyBytes, pushLabel } from './PushToggle';

afterEach(() => cleanup());

describe('keyBytes', () => {
  it('turns URL-safe base64 text into the bytes the browser wants', () => {
    expect(Array.from(keyBytes('AQID'))).toEqual([1, 2, 3]);
    expect(Array.from(keyBytes('-_8'))).toEqual([251, 255]);
  });
});

describe('pushLabel', () => {
  it('says what to show for each state of the browser', () => {
    expect(pushLabel(false, 'default', false)).toEqual({ text: 'This browser cannot show push notifications.', canToggle: false });
    expect(pushLabel(true, 'denied', false).canToggle).toBe(false);
    expect(pushLabel(true, 'default', false)).toEqual({ text: 'Push critical alerts to this device', canToggle: true });
    expect(pushLabel(true, 'granted', true).text).toMatch(/Turn off$/);
  });
});

describe('PushToggle', () => {
  it('explains plainly when the browser cannot do push, with no button', () => {
    render(<PushToggle />);
    expect(screen.getByText('This browser cannot show push notifications.')).toBeTruthy();
    expect(screen.queryByRole('button')).toBeNull();
  });
});
