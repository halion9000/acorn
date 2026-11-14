import { Metadata } from 'next';
import { ComplianceDashboard } from '@/components/compliance/ComplianceDashboard';

export const metadata: Metadata = {
  title: 'Compliance',
};

export default function CompliancePage() {
  return <ComplianceDashboard />;
}
