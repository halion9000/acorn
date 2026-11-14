import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';

const listChildren = vi.fn();
vi.mock('@/lib/api', () => ({ msspApi: { listChildren: (...a: unknown[]) => listChildren(...a) } }));
vi.mock('swr', async () => {
  const React = await import('react');
  return {
    default: (_key: unknown, fetcher: () => Promise<unknown>) => {
      const [data, setData] = React.useState<unknown>(undefined);
      React.useEffect(() => {
        void fetcher().then(setData);
      }, []);
      return { data };
    },
  };
});

import { ClientPicker, homeClientId } from './ClientPicker';

const clients = [
  { id: 'c-acme', name: 'Acme Dental' },
  { id: 'c-home', name: 'Live Oak IT Partners' },
  { id: 'c-birch', name: 'Birch Law' },
];

beforeEach(() => {
  listChildren.mockReset();
  listChildren.mockResolvedValue(clients);
});

describe('ClientPicker', () => {
  it('has no "My organization" line: the organization own company is one of the clients, and the picker starts on it', async () => {
    const onChange = vi.fn();
    render(<ClientPicker value="" onChange={onChange} />);
    const select = await screen.findByRole('combobox', { name: 'Client' });
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual(['Acme Dental', 'Birch Law', 'Live Oak IT Partners']);
    await waitFor(() => expect(onChange).toHaveBeenCalledWith('c-home'));
  });

  it('a page that asks for its own first line (All clients) still gets it, and is not moved off it', async () => {
    const onChange = vi.fn();
    render(<ClientPicker value="" onChange={onChange} ownLabel="All clients" />);
    const select = await screen.findByRole('combobox', { name: 'Client' });
    expect(within(select).getAllByRole('option')[0]).toHaveTextContent('All clients');
    await new Promise((r) => setTimeout(r, 30));
    expect(onChange).not.toHaveBeenCalled();
  });

  it('a client already chosen is left alone', async () => {
    const onChange = vi.fn();
    render(<ClientPicker value="c-birch" onChange={onChange} />);
    await screen.findByRole('combobox', { name: 'Client' });
    await new Promise((r) => setTimeout(r, 30));
    expect(onChange).not.toHaveBeenCalled();
  });

  it('starts on the first client by name when none is called Live Oak IT Partners', () => {
    expect(homeClientId([{ id: 'b', name: 'Birch Law' }, { id: 'a', name: 'Acme Dental' }])).toBe('a');
    expect(homeClientId([])).toBe('');
  });
});
