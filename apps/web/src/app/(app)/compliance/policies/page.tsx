import { Metadata } from 'next';
import { PoliciesView } from '@/components/compliance/PoliciesView';

export const metadata: Metadata = {
  title: 'Compliance policies',
};

export default function CompliancePoliciesPage() {
  return <PoliciesView />;
}
