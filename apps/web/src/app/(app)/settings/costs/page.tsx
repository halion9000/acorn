import type { Metadata } from "next";

import { CostDashboardView } from "@/components/admin/CostDashboardView";

export const metadata: Metadata = {
  title: "Cost dashboard | Settings | A.C.O.R.N",
};

export default function CostDashboardPage() {
  return <CostDashboardView />;
}
