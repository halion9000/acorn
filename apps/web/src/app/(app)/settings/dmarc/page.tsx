import type { Metadata } from "next";

import { DmarcView } from "@/components/dmarc/DmarcView";

export const metadata: Metadata = {
  title: "DMARC reports | Settings | A.C.O.R.N",
};

export default function DmarcPage() {
  return <DmarcView />;
}
