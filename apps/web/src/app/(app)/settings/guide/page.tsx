import type { Metadata } from "next";

import { GuideView } from "@/components/guide/GuideView";

export const metadata: Metadata = {
  title: "ACORN Setup Guide | A.C.O.R.N",
};

export default function SetupGuidePage() {
  return <GuideView />;
}
