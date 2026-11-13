import type { Metadata } from "next";

import { RiskScoringView } from "@/components/vcio/RiskScoringView";

export const metadata: Metadata = {
  title: "Client Risk Score | A.C.O.R.N",
};

export default function VcioRiskScoringPage() {
  return <RiskScoringView />;
}
