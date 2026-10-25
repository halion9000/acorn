import type { Metadata } from "next";

import { Billing } from "./Billing";

export const metadata: Metadata = {
  title: "Licences and counts | Settings | A.C.O.R.N",
};

export default function BillingPage() {
  return <Billing />;
}
