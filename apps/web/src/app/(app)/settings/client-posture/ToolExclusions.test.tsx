import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const authFetch = vi.fn();
vi.mock('@/lib/auth-session', () => ({ authFetch: (...a: unknown[]) => authFetch(...a) }));

import { ToolExclusions, orderedChoices, toggled } from './ToolExclusions';

const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }));
const CHOICES = ['addigy', 'autoelevate', 'dnsfilter', 'fieldeffect', 'huntress', 'ninjaone', 'screenconnect', 'threatmate'];

let saved: string[] = [];
beforeEach(() => {
  authFetch.mockReset();
  saved = [];
  authFetch.mockImplementation((url: string, init?: RequestInit) => {
    if (init?.method === 'PUT') {
      saved = JSON.parse(String(init.body)).tools;
      return json({ tools: saved, choices: CHOICES });
    }
    return json({ tools: saved, choices: CHOICES });
  });
});

describe('helpers', () => {
  it('lists the four tools asked for first and the rest after, in the API order', () => {
    expect(orderedChoices(CHOICES)).toEqual(['huntress', 'screenconnect', 'addigy', 'fieldeffect', 'autoelevate', 'dnsfilter', 'ninjaone', 'threatmate']);
  });
  it('adds or removes one tool without duplicating', () => {
    expect(toggled(['huntress'], 'addigy', true)).toEqual(['huntress', 'addigy']);
    expect(toggled(['huntress'], 'huntress', true)).toEqual(['huntress']);
    expect(toggled(['huntress', 'addigy'], 'huntress', false)).toEqual(['addigy']);
  });
});

describe('ToolExclusions', () => {
  it('shows each tool as a checkbox, ticked for the ones already excluded, and tells the page what was read', async () => {
    saved = ['huntress'];
    const onLoaded = vi.fn();
    render(<ToolExclusions clientId="c1" onLoaded={onLoaded} onChanged={vi.fn()} />);
    expect(await screen.findByLabelText('Huntress')).toBeChecked();
    expect(screen.getByLabelText('Addigy')).not.toBeChecked();
    expect(onLoaded).toHaveBeenCalledWith(['huntress']);
    expect(authFetch.mock.calls[0][0]).toBe('/api/v1/client-posture/c1/tool-exclusions');
  });

  it('ticking a tool saves the whole list for that client and tells the page it changed (not that it loaded)', async () => {
    saved = ['huntress'];
    const onChanged = vi.fn();
    const onLoaded = vi.fn();
    render(<ToolExclusions clientId="c1" onLoaded={onLoaded} onChanged={onChanged} />);
    await userEvent.click(await screen.findByLabelText('ScreenConnect'));
    await waitFor(() => expect(onChanged).toHaveBeenCalledWith(['huntress', 'screenconnect']));
    const put = authFetch.mock.calls.find((c) => c[1]?.method === 'PUT')!;
    expect(put[0]).toBe('/api/v1/client-posture/c1/tool-exclusions');
    expect(JSON.parse(put[1].body)).toEqual({ tools: ['huntress', 'screenconnect'] });
    expect(onLoaded).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText('ScreenConnect')).toBeChecked();
  });

  it('unticking removes it', async () => {
    saved = ['huntress', 'addigy'];
    const onChanged = vi.fn();
    render(<ToolExclusions clientId="c1" onLoaded={vi.fn()} onChanged={onChanged} />);
    await userEvent.click(await screen.findByLabelText('Huntress'));
    await waitFor(() => expect(onChanged).toHaveBeenCalledWith(['addigy']));
  });

  it('says plainly when the person may not change it, and leaves the box as it was', async () => {
    authFetch.mockImplementation((url: string, init?: RequestInit) => (init?.method === 'PUT' ? json({ detail: 'forbidden' }, 403) : json({ tools: [], choices: CHOICES })));
    const onChanged = vi.fn();
    render(<ToolExclusions clientId="c1" onLoaded={vi.fn()} onChanged={onChanged} />);
    await userEvent.click(await screen.findByLabelText('Field Effect'));
    expect(await screen.findByRole('alert')).toHaveTextContent('You need permission to manage clients');
    expect(screen.getByLabelText('Field Effect')).not.toBeChecked();
    expect(onChanged).not.toHaveBeenCalled();
  });

  it('shows the reason the API gives for a refusal', async () => {
    authFetch.mockImplementation((url: string, init?: RequestInit) => (init?.method === 'PUT' ? json({ detail: 'notatool is not a tool that can be excluded' }, 422) : json({ tools: [], choices: CHOICES })));
    render(<ToolExclusions clientId="c1" onLoaded={vi.fn()} onChanged={vi.fn()} />);
    await userEvent.click(await screen.findByLabelText('Addigy'));
    expect(await screen.findByRole('alert')).toHaveTextContent('notatool is not a tool that can be excluded');
  });
});
