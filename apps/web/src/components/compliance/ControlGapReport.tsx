'use client';

/** Under the Controls list: how many controls of each framework have neither accepted evidence nor an owner, who is named for none of them, with the list to download. Counts what the page lists now. */
import { gapCsv, gapReport } from '@/lib/controlGaps';
import { saveText } from '@/lib/saveFile';
import type { ControlRowT } from '@/lib/api';

export function ControlGapReport({ rows }: { rows: ControlRowT[] }) {
  const report = gapReport(rows);
  if (report.length === 0) return null;
  const missing = report.reduce((n, g) => n + g.bothMissing.length, 0);
  return (
    <details className="rounded-lg border border-gray-800 bg-gray-900/40 p-4" data-testid="gap-report">
      <summary className="cursor-pointer text-sm font-medium text-gray-200">
        Gap report: {missing === 0 ? 'every listed control has evidence or an owner' : `${missing} control${missing === 1 ? '' : 's'} with no evidence and no owner`}
      </summary>
      <p className="mt-2 text-xs text-gray-500">Counted over the controls listed above (change the tab, framework or search to change it).</p>
      <table className="mt-2 w-full text-left text-sm">
        <thead className="text-xs uppercase text-gray-500">
          <tr>
            <th className="py-1 pr-3">Framework</th>
            <th className="py-1 pr-3">Controls</th>
            <th className="py-1 pr-3">No evidence</th>
            <th className="py-1 pr-3">No owner</th>
            <th className="py-1">Neither</th>
          </tr>
        </thead>
        <tbody className="text-gray-300">
          {report.map((g) => (
            <tr key={g.framework} className="border-t border-gray-800">
              <td className="py-1 pr-3">{g.framework}</td>
              <td className="py-1 pr-3">{g.total}</td>
              <td className="py-1 pr-3">{g.noEvidence}</td>
              <td className="py-1 pr-3">{g.noOwner}</td>
              <td className={`py-1 ${g.bothMissing.length > 0 ? 'text-red-300' : 'text-emerald-300'}`}>{g.bothMissing.length}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {missing > 0 && (
        <button type="button" onClick={() => void saveText('control-gaps.csv', gapCsv(report))} className="mt-3 rounded border border-gray-700 px-3 py-1 text-xs text-gray-200 hover:bg-gray-800">
          Download the controls with neither (CSV)
        </button>
      )}
    </details>
  );
}
