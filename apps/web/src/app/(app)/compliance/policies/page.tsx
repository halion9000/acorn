import { Metadata } from 'next';
import { SecureframeRegisters } from '@/components/compliance/SecureframeRegisters';
import { GovernancePanel } from '@/components/compliance/GovernancePanel';

export const metadata: Metadata = {
  title: 'Compliance policies',
};

export default function CompliancePoliciesPage() {
  return (
    <div className="space-y-2 p-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Policies</h1>
        <p className="mt-1 text-sm text-gray-400">The written policies and the things that must be reviewed again on a schedule, with an owner and a due date. Policy text is kept in numbered versions.</p>
      </div>
      <SecureframeRegisters show="policies" />
      <GovernancePanel />
    </div>
  );
}
