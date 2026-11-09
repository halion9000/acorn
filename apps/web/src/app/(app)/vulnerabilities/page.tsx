import type { Metadata } from 'next';

import { VulnerabilitiesView } from '@/components/vulnerabilities/VulnerabilitiesView';

export const metadata: Metadata = {
  title: 'Vulnerabilities | A.C.O.R.N',
};

export default function VulnerabilitiesPage() {
  return <VulnerabilitiesView />;
}
