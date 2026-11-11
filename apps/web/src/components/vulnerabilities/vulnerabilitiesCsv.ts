import { csvText } from '@/lib/csv';
import type { Alert } from '@/lib/api';

/** The findings shown on the page as spreadsheet text (what Export CSV saves): severity, client, the finding and its detail, the tool, when it was first seen and the alert it opens. `tool` words the alert's tool as the page does. */
export function vulnerabilitiesCsvText(findings: Alert[], tool: (a: Alert) => string): string {
  return csvText(
    ['Severity', 'Client', 'Finding', 'Details', 'Tool', 'First seen', 'Alert'],
    findings.map((a) => [a.severity, a.clientName ?? '', a.title, a.description ?? '', tool(a), a.createdAt ?? '', `/alerts/${a.id}`]),
  );
}
