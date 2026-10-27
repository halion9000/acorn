import { descriptionBlocks } from './descriptionBlocks';

/** An alert's description: prose, a small table for "Label: value" lines, and formatted code for JSON (see descriptionBlocks). */
export function AlertDescription({ text }: { text: string | null | undefined }) {
  const blocks = descriptionBlocks(text);
  if (blocks.length === 0) return <p className="text-sm text-gray-500">No description.</p>;
  return (
    <div className="space-y-3 text-sm text-gray-300" data-testid="alert-description">
      {blocks.map((b, i) =>
        b.kind === 'text' ? (
          <p key={i} className="whitespace-pre-line leading-relaxed">
            {b.text}
          </p>
        ) : b.kind === 'fields' ? (
          <dl key={i} className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 rounded-lg border border-gray-800 bg-gray-900/40 px-3 py-2">
            {b.rows.map(([label, value], j) => (
              <div key={j} className="contents">
                <dt className="text-gray-500">{label}</dt>
                <dd className="break-words text-gray-200">{value}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <pre key={i} className="overflow-x-auto rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 font-mono text-xs text-gray-300">
            {b.text}
          </pre>
        ),
      )}
    </div>
  );
}
