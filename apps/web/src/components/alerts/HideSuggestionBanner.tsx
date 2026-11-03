'use client';

import useSWR from 'swr';
import { alertsApi } from '@/lib/api';

/** After an alert is closed as a false positive: if people have done that to this alert type several times lately and nothing hides it, say so and offer to hide it. It only offers; the person chooses. */
export function HideSuggestionBanner({ alertId, status, onHide }: { alertId: string; status: string; onHide: () => void }) {
  const { data } = useSWR(status === 'false_positive' ? ['hide-suggestion', alertId] : null, () => alertsApi.hideSuggestion(alertId), { revalidateOnFocus: false, shouldRetryOnError: false });
  if (!data?.suggest) return null;
  return (
    <div role="note" data-testid="hide-suggestion" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-blue-500/40 bg-blue-500/10 p-3 text-sm text-blue-100">
      <span>
        This type of alert has been closed as a false positive {data.false_positives} times in the last {data.days} days. Hide it so it stops reaching you?
      </span>
      <button type="button" onClick={onHide} className="rounded bg-blue-600 px-3 py-1 text-xs text-white hover:bg-blue-500">
        Hide alert type
      </button>
    </div>
  );
}
