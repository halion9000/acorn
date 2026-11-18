import type { Metadata } from 'next';

import { FinanceSettingsView } from '@/components/finance/FinanceSettingsView';

export const metadata: Metadata = {
  title: 'Finance | Settings | A.C.O.R.N',
};

export default function FinanceSettingsPage() {
  return <FinanceSettingsView />;
}
