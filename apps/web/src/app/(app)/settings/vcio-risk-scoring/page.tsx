import type { Metadata } from "next";

import { VcioRiskSettings } from "@/components/settings/VcioRiskSettings";

export const metadata: Metadata = {
  title: "Client Risk Score | Settings | A.C.O.R.N",
};

export default function VcioRiskSettingsPage() {
  return <VcioRiskSettings />;
}
