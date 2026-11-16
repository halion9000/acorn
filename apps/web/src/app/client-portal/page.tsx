import { ClientPortalView } from '@/components/client-portal/ClientPortalView';

export const dynamic = 'force-dynamic';

/** The client dashboard: outside the staff console's layout (no sidebar, no staff pages). */
export default function ClientPortalPage() {
  return <ClientPortalView />;
}
