import type { Metadata } from "next";

import { VcioRiskSettings } from "@/components/settings/VcioRiskSettings";

export const metadata: Metadata = {
  title: "vCIO Risk Scoring | Settings | A.C.O.R.N",
};

export default function VcioRiskSettingsPage() {
  return <VcioRiskSettings />;
}
