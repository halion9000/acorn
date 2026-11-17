import type { Metadata } from 'next';

import { AnnouncementsView } from '@/components/settings/AnnouncementsView';

export const metadata: Metadata = {
  title: 'Announcements | A.C.O.R.N',
};

export default function AnnouncementsPage() {
  return <AnnouncementsView />;
}
