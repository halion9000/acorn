import type { Metadata } from 'next';

import { ComplianceCalendar } from '@/components/compliance/ComplianceCalendar';

export const metadata: Metadata = {
  title: 'Compliance calendar | A.C.O.R.N',
};

export default function ComplianceCalendarPage() {
  return <ComplianceCalendar />;
}
