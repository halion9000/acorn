import { redirect } from 'next/navigation';

/** The cost dashboard lives under Settings now; this keeps old bookmarks and links working. */
export default function CostDashboardMoved(): never {
  redirect('/settings/costs');
}
