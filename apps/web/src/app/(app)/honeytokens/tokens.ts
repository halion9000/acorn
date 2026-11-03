export type TokenStatus = "active" | "triggered" | "expired" | "revoked";

export interface HoneytokenRecord {
  id: string;
  name: string;
  description: string | null;
  token_type: string;
  token_value: string;
  metadata: Record<string, unknown>;
  status: TokenStatus;
  expires_at: string | null;
  created_at: string;
  created_by: string | null;
}

/**
 * What each type is, in plain words, and whether anything can notice it being used. Only a LINK can: opening it calls A.C.O.R.N. The rest are decoy values, and nothing watches for them yet
 * (an AWS key needs CloudTrail, a DNS name a name server, an e-mail address a mailbox, a login the target system's logs), so the page says so instead of letting someone plant one and wait.
 */
export const TOKEN_TYPES: Record<string, { label: string; alerts: boolean; plant: string }> = {
  url: {
    label: "Link",
    alerts: true,
    plant: 'Put this link where only an intruder would click it: a wiki page called "Passwords", a note in a shared folder, a README. Anyone who opens it raises an alert.',
  },
  file: {
    label: "Document with a link",
    alerts: true,
    plant: "Create a document that looks valuable (a fake backup, a salary sheet) and put the beacon link inside it as a hyperlink or image. Opening the link, or a viewer loading it, raises an alert. Plain text files never load links.",
  },
  aws_key: {
    label: "AWS key (decoy only)",
    alerts: false,
    plant: "A fake key that looks real. Nothing watches for it being used yet: AWS would have to report the attempt (CloudTrail) to A.C.O.R.N. Plant it only to keep a record of what you hid.",
  },
  db_credential: {
    label: "Database login (decoy only)",
    alerts: false,
    plant: "A fake database login. Nothing watches for it yet: that database's logs would have to be sent to A.C.O.R.N.",
  },
  email: {
    label: "E-mail address (decoy only)",
    alerts: false,
    plant: "A fake address. Nothing watches for mail to it yet: a mailbox A.C.O.R.N can read would be needed.",
  },
  dns: {
    label: "DNS name (decoy only)",
    alerts: false,
    plant: "A fake name. Nothing watches for lookups of it yet: a name server you run would be needed.",
  },
  api_key: {
    label: "API key (decoy only)",
    alerts: false,
    plant: "A fake key. Nothing watches for it being used yet.",
  },
  custom: {
    label: "Custom value (decoy only)",
    alerts: false,
    plant: "A random value. Nothing watches for it yet.",
  },
};

export const TOKEN_TYPE_ORDER = ["url", "file", "aws_key", "db_credential", "email", "dns", "api_key", "custom"];

/** The values to copy and plant, from a token's stored data: the link first, then the rest. */
export function plantables(token: Pick<HoneytokenRecord, "metadata">): Array<[string, string]> {
  const data = (token.metadata?.token_data ?? {}) as Record<string, unknown>;
  const order = ["url", "beacon_url", "filename", "access_key_id", "secret_access_key", "username", "password", "host", "email", "fqdn", "api_key", "value", "checksum"];
  const keys = [...order.filter((k) => k in data), ...Object.keys(data).filter((k) => !order.includes(k))];
  return keys.filter((k) => data[k] !== null && data[k] !== undefined && String(data[k]) !== "").map((k) => [k, String(data[k])]);
}

/** A file name made only of letters, digits, spaces, dots, dashes and underscores (so it cannot carry a path or a quote into the script). */
export function safeFileName(name: string): string {
  const cleaned = name.replace(/[^A-Za-z0-9 ._-]/g, "").replace(/\s+/g, " ").trim().replace(/^\.+/, "");
  return cleaned.slice(0, 80) || "Document";
}

/**
 * A PowerShell script that plants a token's link on a Windows computer as an internet shortcut (a .url file) in a folder the person edits first, for pasting into a remote script tool such as NinjaOne's.
 * Only for a token that can alert (a link), and only when the link is a plain web address: anything else returns null rather than a script that could carry a stray quote or command.
 */
export function plantScript(token: Pick<HoneytokenRecord, "name" | "token_type" | "metadata">): string | null {
  if (!canAlert(token)) return null;
  const link = plantables(token).find(([k]) => k === "url" || k === "beacon_url")?.[1];
  if (!link || !/^https?:\/\/[^\s'"`$;|&<>()]+$/.test(link)) return null;
  const file = safeFileName(token.name);
  return [
    "# Plants a tripwire shortcut. Opening it calls A.C.O.R.N and raises an alert. Change the folder, then run it as the person or as SYSTEM.",
    "$folder = 'C:\\Users\\Public\\Documents'",
    `$file = '${file}.url'`,
    "if (-not (Test-Path -LiteralPath $folder)) { New-Item -ItemType Directory -Path $folder -Force | Out-Null }",
    "$path = Join-Path $folder $file",
    `Set-Content -LiteralPath $path -Value @('[InternetShortcut]', 'URL=${link}') -Encoding ASCII`,
    "Write-Output \"Planted $path\"",
    "",
  ].join("\r\n");
}

/** Whether anything will notice this token being used. The service says so when it makes the token; a token made before that label existed is judged by its type. */
export function canAlert(token: Pick<HoneytokenRecord, "token_type" | "metadata">): boolean {
  const stored = token.metadata?.detection;
  if (stored === "link") return true;
  if (stored === "none") return false;
  return TOKEN_TYPES[token.token_type]?.alerts ?? false;
}
