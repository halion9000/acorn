"use client";

/**
 * How to plant a honeytoken, on the Honeytokens page itself, behind a "How to" button: what each part does, the steps, the PowerShell that places a link on a Windows computer, where to put it, what works
 * inside the network and what only works once a public address exists, and how to test it.
 */
import { useState } from "react";

/** The PowerShell that makes a shortcut file opening the token's link. The link is pasted in by the person; nothing here knows any token. */
export const PLANT_SCRIPT = [
  "$link = 'PASTE THE TOKEN LINK HERE'",
  "Set-Content -Path 'C:\\Users\\Public\\Documents\\Admin passwords backup.url' -Value \"[InternetShortcut]`r`nURL=$link\" -Encoding ascii",
].join("\n");

export function HowTo({ onClose }: { onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard?.writeText(PLANT_SCRIPT);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };
  return (
    <section aria-label="How to plant a honeytoken" data-testid="howto" className="mb-6 rounded-lg border border-sky-500/40 bg-sky-500/5 p-5 text-sm text-gray-300">
      <div className="mb-3 flex items-start justify-between gap-3">
        <h2 className="text-base font-semibold text-gray-100">How to plant a honeytoken</h2>
        <button type="button" onClick={onClose} className="text-xs text-gray-400 hover:text-gray-200">
          Close
        </button>
      </div>

      <h3 className="mt-2 font-medium text-gray-100">What it is</h3>
      <p className="mt-1 text-gray-400">
        A honeytoken is bait. You put a link where only an intruder would look. A normal user has no reason to open it, so when someone does, A.C.O.R.N records their address and browser and raises a high alert in that
        client&apos;s queue (at most one alert per token per hour). Only the <strong className="text-gray-200">Link</strong> and <strong className="text-gray-200">Document with a link</strong> types can do this. The others are decoy
        values that nothing watches yet.
      </p>

      <h3 className="mt-4 font-medium text-gray-100">Steps</h3>
      <ol className="mt-1 list-decimal space-y-1.5 pl-5">
        <li>
          Click <strong className="text-gray-200">+ New Token</strong>. Pick <strong className="text-gray-200">Link</strong> (or <strong className="text-gray-200">Document with a link</strong>) and name it for the place you will plant it,
          for example &ldquo;Acme server, Public Documents&rdquo;. Use one token per place: the alert then says exactly which place was touched.
        </li>
        <li>
          Open the token&apos;s <strong className="text-gray-200">Details</strong> and copy its link. It looks like <code className="text-gray-400">https://acorn.goliveoak.com/api/v1/canary/&hellip;</code>.
        </li>
        <li>Put the link in the place you named, using one of the ways below.</li>
        <li>
          Test it: open the link yourself from a computer on your network. The token turns to <em>triggered</em> and an alert appears within seconds. Then plant it for real.
        </li>
      </ol>

      <h3 className="mt-4 font-medium text-gray-100">Ways to plant it</h3>
      <ul className="mt-1 list-disc space-y-1.5 pl-5">
        <li>
          <strong className="text-gray-200">A shortcut file on a computer or file server.</strong> Run this PowerShell on that computer (by hand, or through NinjaOne&apos;s script tool), with the token&apos;s link pasted in. Double-clicking
          the file opens the link.
          <div className="mt-2 flex items-start gap-2">
            <pre className="flex-1 overflow-x-auto rounded border border-gray-700 bg-gray-950 p-2 text-xs text-gray-200" data-testid="howto-script">
              {PLANT_SCRIPT}
            </pre>
            <button type="button" onClick={() => void copy()} className="rounded border border-sky-500/50 px-2 py-1 text-xs text-sky-300">
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
        </li>
        <li>
          <strong className="text-gray-200">A wiki or IT Glue note.</strong> Make a page called &ldquo;Passwords&rdquo; or &ldquo;Old admin logins&rdquo; and put the link in it as a hyperlink.
        </li>
        <li>
          <strong className="text-gray-200">A document.</strong> For a <em>Document with a link</em> token, make a Word or Excel file that looks valuable (&ldquo;Salary sheet&rdquo;, &ldquo;VPN keys&rdquo;) and put the link in it as a
          hyperlink or a picture. Plain text files never open links, so a <code className="text-gray-400">.txt</code> will not alert.
        </li>
      </ul>

      <h3 className="mt-4 font-medium text-gray-100">Where not to put it</h3>
      <p className="mt-1 text-gray-400">
        Not where your own staff, backups or antivirus open every file: a scanner that opens the link raises a false alarm. A folder nobody has a reason to open, with a name that tempts, is best.
      </p>

      <h3 className="mt-4 font-medium text-gray-100">Inside or outside your network</h3>
      <ul className="mt-1 list-disc space-y-1.5 pl-5">
        <li>
          <strong className="text-gray-200">Inside, as it works today:</strong> the link&apos;s address only resolves on your network or VPN. Someone snooping there triggers it. A file taken off-site and opened at home does not.
        </li>
        <li>
          <strong className="text-gray-200">Outside:</strong> needs a public address that forwards only <code className="text-gray-400">/api/v1/canary/*</code> to A.C.O.R.N, set as the base address for new tokens. You plant the
          same way; tokens made before that change keep the old address, so make new ones and re-plant.
        </li>
      </ul>

      <p className="mt-4 text-xs text-gray-500">The decoy types (AWS key, database login, e-mail address, DNS name, API key, custom value) only keep a record of what you hid. Nothing watches for them being used yet.</p>
    </section>
  );
}
