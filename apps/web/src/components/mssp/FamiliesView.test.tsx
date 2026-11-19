import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('next/link', () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));

const api = vi.hoisted(() => ({
  listFamilies: vi.fn(),
  listChildren: vi.fn(),
  createFamily: vi.fn(),
  changeFamily: vi.fn(),
  deleteFamily: vi.fn(),
}));
vi.mock('@/lib/api', () => ({ msspApi: api }));

import FamiliesView from './FamiliesView';

const kids = [
  { id: 'a', name: 'NW - North' },
  { id: 'b', name: 'NW - South' },
  { id: 'c', name: 'Other Co' },
];

beforeEach(() => {
  Object.values(api).forEach((m) => m.mockReset());
  api.listChildren.mockResolvedValue(kids);
  api.listFamilies.mockResolvedValue([]);
});
afterEach(() => cleanup());

describe('FamiliesView', () => {
  it('says there are no families and creates one from the picked clients', async () => {
    api.createFamily.mockResolvedValue({ id: 'f', name: 'New Waterloo', client_ids: ['a', 'b'], clients: ['NW - North', 'NW - South'] });
    render(<FamiliesView />);
    expect(await screen.findByText('No families yet')).toBeTruthy();
    await userEvent.type(screen.getByLabelText('Family name'), 'New Waterloo');
    await userEvent.click(screen.getByLabelText('NW - North'));
    await userEvent.click(screen.getByLabelText('NW - South'));
    await userEvent.click(screen.getByRole('button', { name: 'Create family' }));
    await waitFor(() => expect(api.createFamily).toHaveBeenCalledWith('New Waterloo', ['a', 'b']));
  });

  it('lists a family, offers only clients in no family, takes one out and shows the server refusal', async () => {
    api.listFamilies.mockResolvedValue([{ id: 'f', name: 'New Waterloo', client_ids: ['a', 'b'], clients: ['NW - North', 'NW - South'] }]);
    api.changeFamily.mockRejectedValue(new Error('One of the clients is already in another family.'));
    render(<FamiliesView />);
    expect(await screen.findByText('New Waterloo')).toBeTruthy();
    const add = screen.getByLabelText('Add a client to New Waterloo') as HTMLSelectElement;
    expect(Array.from(add.options).map((o) => o.text)).toEqual(['Pick a client', 'Other Co']);
    await userEvent.click(screen.getByRole('button', { name: 'Take NW - North out of New Waterloo' }));
    await waitFor(() => expect(api.changeFamily).toHaveBeenCalledWith('f', { client_ids: ['b'] }));
    expect((await screen.findByRole('alert')).textContent).toContain('already in another family');
  });
});
