import { ExecutiveDigest } from '@/components/reports/ExecutiveDigest';
import { ReportSchedules } from '@/components/reports/ReportSchedules';

export const metadata = { title: 'Executive Digest' };

export default function ExecutiveDigestPage() {
  return (
    <div className="p-6 max-w-7xl mx-auto">
      <ExecutiveDigest />
      <ReportSchedules />
    </div>
  );
}
