import type { Metadata } from "next";

import { NessusView } from "@/components/nessus/NessusView";

export const metadata: Metadata = {
  title: "Vulnerability scans | Settings | A.C.O.R.N",
};

export default function NessusPage() {
  return <NessusView />;
}
