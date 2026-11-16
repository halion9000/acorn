import type { Metadata } from 'next';

import { WhatsNewView } from '@/components/settings/WhatsNewView';

export const metadata: Metadata = {
  title: "What's new | A.C.O.R.N",
};

export default function WhatsNewPage() {
  return <WhatsNewView />;
}
