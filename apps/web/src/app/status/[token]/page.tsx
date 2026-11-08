import type { Metadata } from 'next';
import { notFound } from 'next/navigation';

import { fetchClientStatus } from '../../../lib/client-status';
import { StatusView } from './StatusView';

interface PageProps {
  params: Promise<{ token: string }>;
}

// A private page: never indexed, never cached, and the same 404 for a wrong, revoked, expired or unreviewed link.
export const dynamic = 'force-dynamic';
export const metadata: Metadata = { title: 'Security status', robots: { index: false, follow: false } };

export default async function ClientStatusPageRoute({ params }: PageProps) {
  const { token } = await params;
  const page = await fetchClientStatus(token);
  if (!page) notFound();
  return <StatusView page={page} />;
}
