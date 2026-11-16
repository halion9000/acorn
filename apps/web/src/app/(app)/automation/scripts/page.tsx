import type { Metadata } from "next";

import { ScriptLog } from "@/components/automation/ScriptLog";
import { ScriptRules } from "@/components/automation/ScriptRules";

export const metadata: Metadata = {
  title: "Auto Scripts | Automation | A.C.O.R.N",
};

export default function AutoScriptsPage() {
  return (
    <div className="pt-6">
      <ScriptRules />
      <ScriptLog />
    </div>
  );
}
