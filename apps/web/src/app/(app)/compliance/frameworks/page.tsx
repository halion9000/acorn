import { Metadata } from 'next';
import { FrameworkIndex } from '@/components/compliance/FrameworkIndex';
import { FRAMEWORK_LIST } from '@/components/compliance/frameworkList';

export const metadata: Metadata = {
  title: 'Compliance frameworks',
};

export default function ComplianceFrameworksPage() {
  return <FrameworkIndex frameworks={FRAMEWORK_LIST} />;
}
