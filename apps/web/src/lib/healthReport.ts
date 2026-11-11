/**
 * The Platform health page as a file to attach to a support ticket: what the page already shows (versions, services, workers, warnings), with the moment it was made.
 * The server puts no secret in that snapshot; as a second guard, any text under a field whose name looks like a secret is blanked before the file is written.
 */
const SECRET_NAME = /(secret|token|password|passwd|credential|api[_-]?key|private[_-]?key|authorization)/i;

/** Fields that only describe a credential (its name, kind, expiry date or status) and so stay readable even under a secret-looking name: the page's own `microsoft_secret` row is `expires_on` and `days_left`, and an old credential is a `kind` and an age. A field called `value`, `key` or `token` is not here and is blanked. */
const DESCRIBES = /^(name|kind|label|title|status|state|expires|expires_on|expires_at|expiry|expiry_date)$/i;

/** A copy of the value with text under a secret-looking field name replaced. Field names stay, so the report still shows that the field was there. */
export function scrubbed(value: unknown, underSecretName = false): unknown {
  if (Array.isArray(value)) return value.map((v) => scrubbed(v, underSecretName));
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, scrubbed(v, (underSecretName && !DESCRIBES.test(k)) || SECRET_NAME.test(k))]));
  }
  if (underSecretName && typeof value === 'string' && value !== '') return '[removed]';
  return value;
}

export function healthReport(snapshot: unknown, now: Date): string {
  return JSON.stringify({ report: 'A.C.O.R.N platform health', made: now.toISOString(), note: 'No passwords, keys or tokens are included.', snapshot: scrubbed(snapshot) }, null, 2);
}

export function healthReportFileName(now: Date): string {
  return `acorn-health-${now.toISOString().slice(0, 16).replace(/[:T]/g, '-')}.json`;
}
