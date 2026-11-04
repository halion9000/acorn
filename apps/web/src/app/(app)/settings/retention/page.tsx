import type { Metadata } from "next";

import { DataRetention } from "@/components/settings/DataRetention";

export const metadata: Metadata = {
  title: "Data retention | Settings | A.C.O.R.N",
};

export default function DataRetentionPage() {
  return <DataRetention />;
}
