import { Suspense } from 'react';
import ClientEnvironmentView from '@/components/devices/ClientEnvironmentView';

export const metadata = { title: 'Client environment' };

export default function ClientEnvironmentPage() {
  // The view reads ?client= through the router, which needs a Suspense boundary.
  return (
    <Suspense fallback={null}>
      <ClientEnvironmentView />
    </Suspense>
  );
}
