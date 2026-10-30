import type { Metadata } from "next";

import { InventoryView } from "@/components/inventory/InventoryView";

export const metadata: Metadata = {
  title: "Inventory | A.C.O.R.N",
};

export default function InventoryPage() {
  return <InventoryView />;
}
