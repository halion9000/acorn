import type { Metadata } from 'next';

import { MyPoliciesView } from '@/components/compliance/MyPoliciesView';

export const metadata: Metadata = {
  title: 'My policies | A.C.O.R.N',
};

export default function MyPoliciesPage() {
  return <MyPoliciesView />;
}
