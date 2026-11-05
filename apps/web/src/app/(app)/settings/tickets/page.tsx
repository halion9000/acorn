import type { Metadata } from "next";

import { TicketRules } from "./TicketRules";
import { TicketSettings } from "./TicketSettings";

export const metadata: Metadata = {
  title: "Tickets | Settings | A.C.O.R.N",
};

export default function TicketSettingsPage() {
  return (
    <>
      <TicketSettings />
      <TicketRules />
    </>
  );
}
