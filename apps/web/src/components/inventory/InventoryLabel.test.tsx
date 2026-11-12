import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { InventoryItem } from '@/lib/api';
import { InventoryLabel } from './InventoryLabel';
import { labelAddress, labelLines, labelSearch } from './labelText';

const item = (over: Partial<InventoryItem> = {}): InventoryItem =>
  ({ id: 'i1', kind: 'stock', name: 'Latitude 5440', serial: 'ABC123', model: '5440', manufacturer: 'Dell', client_name: 'Acme Dental', customer_name: null, ...over }) as InventoryItem;

describe('labelSearch and labelAddress', () => {
  it('searches by serial when there is one, else by name, trimmed and cut to what a link reads', () => {
    expect(labelSearch(item())).toBe('ABC123');
    expect(labelSearch(item({ serial: '  ' }))).toBe('Latitude 5440');
    expect(labelSearch(item({ serial: null, name: 'x'.repeat(150) }))).toHaveLength(100);
  });

  it('opens the inventory page on the item, with the kind only for a NUC, and encodes what it searches for', () => {
    expect(labelAddress('https://acorn.example', item())).toBe('https://acorn.example/inventory?search=ABC123');
    expect(labelAddress('https://acorn.example/', item({ kind: 'nuc' }))).toBe('https://acorn.example/inventory?search=ABC123&kind=nuc');
    const odd = labelAddress('https://acorn.example', item({ serial: null, name: 'PC 1 & 2/#' }));
    expect(new URL(odd).searchParams.get('search')).toBe('PC 1 & 2/#');
  });
});

describe('labelLines', () => {
  it('gives the name, maker and model, serial and holder, leaving out what the item does not have', () => {
    expect(labelLines(item())).toEqual(['Latitude 5440', 'Dell 5440', 'S/N ABC123', 'Acme Dental']);
    expect(labelLines(item({ manufacturer: null, model: null, serial: null, client_name: null, customer_name: 'Birch Co' }))).toEqual(['Latitude 5440', 'Birch Co']);
    expect(labelLines(item({ client_name: null, customer_name: null, manufacturer: null }))).toEqual(['Latitude 5440', '5440', 'S/N ABC123', 'Live Oak']);
  });
});

describe('InventoryLabel', () => {
  it('shows the lines, a QR code, the address it opens, and prints or closes on the buttons', async () => {
    const print = vi.fn();
    const onClose = vi.fn();
    render(<InventoryLabel item={item()} origin="https://acorn.example" onClose={onClose} print={print} />);
    expect(screen.getAllByTestId('label-line').map((l) => l.textContent)).toEqual(['Latitude 5440', 'Dell 5440', 'S/N ABC123', 'Acme Dental']);
    expect((await screen.findByTestId('label-qr')).querySelector('svg')).not.toBeNull();
    expect(screen.getByTestId('label-address')).toHaveTextContent('https://acorn.example/inventory?search=ABC123');
    await userEvent.click(screen.getByRole('button', { name: 'Print label' }));
    expect(print).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
