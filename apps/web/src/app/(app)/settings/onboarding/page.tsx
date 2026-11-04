import type { Metadata } from "next";

import { ClientOnboarding } from "@/components/settings/ClientOnboarding";

export const metadata: Metadata = {
  title: "Client onboarding | Settings | A.C.O.R.N",
};

export default function ClientOnboardingPage() {
  return <ClientOnboarding />;
}
