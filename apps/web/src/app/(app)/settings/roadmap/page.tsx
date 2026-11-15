import type { Metadata } from 'next';

import { RoadmapView } from '@/components/settings/RoadmapView';

export const metadata: Metadata = {
  title: 'Upcoming improvements | A.C.O.R.N',
};

export default function RoadmapPage() {
  return <RoadmapView />;
}
