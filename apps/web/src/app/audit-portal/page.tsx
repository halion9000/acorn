import { AuditPortalView } from '@/components/audit-portal/AuditPortalView';

export const dynamic = 'force-dynamic';

/** The auditor's pages: outside the staff console's layout (no sidebar, no staff pages). */
export default function AuditPortalPage() {
  return <AuditPortalView />;
}
