import type { Metadata } from "next";

import { TicketRules } from "@/components/automation/TicketRules";

export const metadata: Metadata = {
  title: "Auto Tickets | Automation | A.C.O.R.N",
};

export default function AutoTicketsPage() {
  return (
    <div className="pt-6">
      <TicketRules />
    </div>
  );
}
