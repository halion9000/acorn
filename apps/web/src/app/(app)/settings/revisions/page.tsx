import type { Metadata } from 'next';

import { RevisionsView } from '@/components/settings/RevisionsView';

export const metadata: Metadata = {
  title: 'Revisions | A.C.O.R.N',
};

export default function RevisionsPage() {
  return <RevisionsView />;
}
