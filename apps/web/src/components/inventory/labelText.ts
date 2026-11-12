import type { InventoryItem } from '@/lib/api';

type LabelItem = Pick<InventoryItem, 'kind' | 'name' | 'serial' | 'model' | 'manufacturer' | 'client_name' | 'customer_name'>;

/** What the label's QR code searches for: the serial when the item has one (it is unique), else the name; at most 100 characters, the most the page reads from a link. */
export function labelSearch(item: Pick<InventoryItem, 'name' | 'serial'>): string {
  return (item.serial?.trim() || item.name.trim()).slice(0, 100);
}

/** The address the QR code opens: the inventory page already showing this item. `origin` is the site's own address (https://host), never one from the item. */
export function labelAddress(origin: string, item: Pick<InventoryItem, 'kind' | 'name' | 'serial'>): string {
  const params = new URLSearchParams({ search: labelSearch(item) });
  if (item.kind === 'nuc') params.set('kind', 'nuc');
  return `${origin.replace(/\/+$/, '')}/inventory?${params.toString()}`;
}

/** The text lines printed beside the code: the name, then the maker and model, the serial, and who it is held for. A line the item has nothing for is left out. */
export function labelLines(item: LabelItem): string[] {
  const maker = [item.manufacturer, item.model].map((s) => s?.trim()).filter(Boolean).join(' ');
  const holder = item.client_name?.trim() || item.customer_name?.trim() || 'Live Oak';
  return [item.name.trim(), maker, item.serial?.trim() ? `S/N ${item.serial.trim()}` : '', holder].filter((line) => line !== '');
}
