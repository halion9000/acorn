import type { Metadata } from "next";

import { CippActions } from "./CippActions";

export const metadata: Metadata = {
  title: "CIPP actions | Settings | A.C.O.R.N",
};

export default function CippActionsPage() {
  return <CippActions />;
}
