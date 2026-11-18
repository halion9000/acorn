import type { Metadata } from 'next';

import { DeviceVersions } from '@/components/devices/DeviceVersions';

export const metadata: Metadata = {
  title: 'Device versions | A.C.O.R.N',
};

export default function DeviceVersionsPage() {
  return <DeviceVersions />;
}
