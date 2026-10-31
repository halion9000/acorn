import type { Metadata } from "next";
import { Suspense } from "react";

import { InventoryView } from "@/components/inventory/InventoryView";

export const metadata: Metadata = {
  title: "Inventory | A.C.O.R.N",
};

export default function InventoryPage() {
  // InventoryView reads the address (?search=, ?kind=, ?client=) through the router, which needs a Suspense boundary.
  return (
    <Suspense fallback={null}>
      <InventoryView />
    </Suspense>
  );
}
