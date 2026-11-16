import type { Metadata } from "next";

import { HubSpotAutomations } from "@/components/automation/HubSpotAutomations";

export const metadata: Metadata = {
  title: "HubSpot | Automation | A.C.O.R.N",
};

export default function HubSpotAutomationPage() {
  return <HubSpotAutomations />;
}
