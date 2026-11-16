import type { Metadata } from "next";

import Link from "next/link";

import { ToolInstalls } from "./ToolInstalls";
import { TicketSettings } from "./TicketSettings";

export const metadata: Metadata = {
  title: "Tickets | Settings | A.C.O.R.N",
};

export default function TicketSettingsPage() {
  return (
    <>
      <TicketSettings />
      <p className="mx-auto max-w-2xl px-6 text-sm text-gray-400" data-testid="automation-moved">
        The automatic ticket rules, the automatic script rules and the script log are now under <Link href="/automation/tickets" className="text-blue-300 hover:underline">Automation</Link> in the menu.
      </p>
      <ToolInstalls />
    </>
  );
}
