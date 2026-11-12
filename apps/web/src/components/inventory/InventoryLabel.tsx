'use client';

/**
 * A printable label for one inventory item: a QR code that opens the inventory page on that item, with its name, maker and model, serial and who it is held for. The code is drawn in the
 * browser; nothing about the item is sent anywhere. Print hides everything on the page but the label.
 */
import { useEffect, useState } from 'react';
import QRCode from 'qrcode';
import type { InventoryItem } from '@/lib/api';
import { labelAddress, labelLines } from './labelText';

const PRINT_ONLY_LABEL = '@media print { body * { visibility: hidden !important; } #inventory-label, #inventory-label * { visibility: visible !important; } #inventory-label { position: fixed; left: 0; top: 0; } }';

export function InventoryLabel({ item, origin, onClose, print = () => window.print() }: { item: InventoryItem; origin: string; onClose: () => void; print?: () => void }) {
  const address = labelAddress(origin, item);
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    QRCode.toString(address, { type: 'svg', margin: 1, width: 132, errorCorrectionLevel: 'M' })
      .then((s) => live && setSvg(s))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [address]);
  const lines = labelLines(item);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-label={`Label for ${item.name}`}>
      <style>{PRINT_ONLY_LABEL}</style>
      <div className="w-full max-w-md rounded-lg border border-gray-700 bg-gray-900 p-4">
        <div id="inventory-label" data-testid="inventory-label" className="flex items-center gap-3 rounded bg-white p-3 text-black">
          {/* The markup is produced by the QR library from the address above and holds only shapes, no scripts or text from outside. */}
          {svg ? <div role="img" aria-label="QR code that opens this item in the inventory" data-testid="label-qr" dangerouslySetInnerHTML={{ __html: svg }} /> : null}
          <div className="min-w-0 text-xs leading-snug">
            {lines.map((line, i) => (
              <div key={`${i}-${line}`} className={i === 0 ? 'text-sm font-semibold' : ''} data-testid="label-line">
                {line}
              </div>
            ))}
          </div>
        </div>
        {failed ? (
          <p className="mt-2 text-xs text-amber-300" data-testid="label-problem">
            The QR code could not be drawn. The label can still be printed with its text.
          </p>
        ) : null}
        <p className="mt-2 break-all text-xs text-gray-400" data-testid="label-address">
          Scanning it opens {address}
        </p>
        <div className="mt-3 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-md border border-gray-700 px-3 py-1.5 text-sm text-gray-300">
            Close
          </button>
          <button type="button" onClick={() => print()} className="rounded-md bg-sky-600 px-3 py-1.5 text-sm text-white">
            Print label
          </button>
        </div>
      </div>
    </div>
  );
}
