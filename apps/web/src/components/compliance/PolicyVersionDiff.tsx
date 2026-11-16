'use client';

/** What changed in a policy between a version and the one before it: removed lines in red, added lines in green, unchanged lines dimmed. Built from the two texts already on the page (lib/textDiff.ts). */
import { diffCounts, lineDiff } from '@/lib/textDiff';

export function PolicyVersionDiff({ version, before, after }: { version: number; before: string; after: string }) {
  const diff = lineDiff(before, after);
  const { added, removed } = diffCounts(diff);
  return (
    <div className="mt-1 rounded border border-gray-700 bg-gray-950 p-2" data-testid="policy-diff">
      <p className="text-gray-400">
        Version {version - 1} to version {version}: {added} line{added === 1 ? '' : 's'} added, {removed} removed.
      </p>
      {added === 0 && removed === 0 ? (
        <p className="mt-1 text-gray-500">The text is the same.</p>
      ) : (
        <pre className="mt-1 whitespace-pre-wrap font-mono">
          {diff.map((l, k) => (
            <div key={k} className={l.kind === 'add' ? 'bg-emerald-500/10 text-emerald-300' : l.kind === 'del' ? 'bg-red-500/10 text-red-300 line-through' : 'text-gray-500'}>
              {l.kind === 'add' ? '+ ' : l.kind === 'del' ? '- ' : '  '}
              {l.text}
            </div>
          ))}
        </pre>
      )}
    </div>
  );
}
