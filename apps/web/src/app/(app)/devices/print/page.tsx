import { Suspense } from 'react';
import PrintInventory from '@/components/devices/PrintInventory';

export const metadata = { title: 'Device inventory' };

export default function PrintInventoryPage() {
  // The view reads ?client= through the router, which needs a Suspense boundary.
  return (
    <Suspense fallback={null}>
      <PrintInventory />
    </Suspense>
  );
}
