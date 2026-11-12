import type { Metadata } from "next";

import { RiskScoringView } from "@/components/vcio/RiskScoringView";

export const metadata: Metadata = {
  title: "vCIO Risk Scoring | A.C.O.R.N",
};

export default function VcioRiskScoringPage() {
  return <RiskScoringView />;
}
