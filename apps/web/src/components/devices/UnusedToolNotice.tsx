'use client';

/** On Devices, for one chosen client: a tool that none of its computers has is probably a tool it does not use. Says so and links to the posture page where "tools this client does not use" is ticked. */
import Link from 'next/link';
import { vendorLabel } from '@/components/mssp/ClientMapping';
import { unusedToolHints } from '@/lib/unusedToolHints';

export function UnusedToolNotice({ clientId, summary, excluded }: { clientId: string; summary: Parameters<typeof unusedToolHints>[0] | undefined; excluded: string[] }) {
  if (!clientId || !summary) return null;
  const hints = unusedToolHints(summary, excluded);
  if (hints.length === 0) return null;
  return (
    <div role="note" data-testid="unused-tool-notice" className="rounded-lg border border-sky-500/30 bg-sky-500/5 px-3 py-2 text-sm text-sky-100">
      {hints.map((h) => vendorLabel(h.tool)).join(', ')}: none of this client&apos;s {hints[0]!.computers} computers {hints.length === 1 ? 'has it' : 'have them'}. If the client does not use {hints.length === 1 ? 'it' : 'them'}, tick{' '}
      <Link href={`/settings/client-posture?client=${encodeURIComponent(clientId)}`} className="underline">
        Tools this client does not use
      </Link>{' '}
      so {hints.length === 1 ? 'it stops' : 'they stop'} counting as a gap.
    </div>
  );
}
