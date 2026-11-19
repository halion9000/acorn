'use client';

/**
 * Settings > Scorecard: the weighted template the service desk scorecard is worked out with (read only), so a person can see exactly why a week scored what it did: each metric's weight and share, the brackets that turn a
 * number into 1-5, the table used for each number of days worked, and the grade cut-offs.
 */
import Link from 'next/link';

import { Page, Panel, Table, useMetric } from './kit';

export interface TemplateMetric {
  metric: string;
  unit: string;
  weight: number;
  share: number;
  floor: number;
  by_days_worked: boolean;
  tables: Record<string, [number, number][]>;
}
export interface Template {
  metrics: TemplateMetric[];
  total_weight: number;
  grades: { grade: string; from: number }[];
}

/** A bracket table as a sentence for a cell: "30 or more: 5". */
export const bracketText = (threshold: number, score: number): string => `${threshold} or more: ${score}`;

/** The worked example shown under the weights: each metric's score times its weight, added up and divided by the total weight (pure). */
export function worked(metrics: TemplateMetric[], scores: Record<string, number>): { rows: { metric: string; score: number; weight: number; points: number }[]; total: number } {
  const rows = metrics.filter((m) => scores[m.metric] !== undefined).map((m) => ({ metric: m.metric, score: scores[m.metric]!, weight: m.weight, points: scores[m.metric]! * m.weight }));
  const weight = rows.reduce((a, r) => a + r.weight, 0);
  return { rows, total: weight > 0 ? Math.round((rows.reduce((a, r) => a + r.points, 0) / weight) * 10) / 10 : 0 };
}

const EXAMPLE: Record<string, number> = { 'Tickets Closed': 4, 'Tickets Updated': 5, 'Labor Hours': 4, 'Calls Made': 3, 'Call Time': 3, CSAT: 5, Utilization: 3 };

export function ScorecardSettingsView() {
  const { data, denied, problem } = useMetric<Template>('/api/v1/reports/metrics/scorecard-template');
  const example = data ? worked(data.metrics, EXAMPLE) : null;
  return (
    <Page title="Scorecard settings" subtitle="The weighted template the service desk scorecard is worked out with: how much each measure counts, the brackets that turn a number into a score from 1 to 5, and the grade cut-offs." denied={denied} problem={problem} loading={data === null && !denied && !problem} empty={null}>
      <p className="text-sm">
        <Link href="/metrics/scorecard" className="text-blue-300 underline">
          Back to the scorecard
        </Link>
      </p>
      {data && (
        <div className="space-y-4">
          <Panel title="How a week is scored" testId="score-how">
            <ol className="list-decimal space-y-1 pl-5 text-sm">
              <li>Each measure for the week is turned into a score from 1 to 5 using its brackets below. The highest bracket whose number the week reaches gives the score; a week below the lowest bracket gets the floor.</li>
              <li>Measures that count per day (tickets, labor hours, calls, call time) use the table for the number of days the person worked that week, so a part week is judged fairly.</li>
              <li>Each score is multiplied by the measure&apos;s weight, the results are added up and divided by the weights of the measures that had something to score (a week with no surveys leaves CSAT out).</li>
              <li>The week&apos;s score is rounded to one decimal. A week with no activity, or a full week off, is not scored. A person&apos;s average is the average of their scored weeks.</li>
            </ol>
          </Panel>
          <Panel title="Weights" testId="score-weights">
            <Table
              head={['Measure', 'Counted as', 'Weight', 'Share of the score', 'Floor']}
              rows={data.metrics.map((m) => [m.metric, m.unit, String(m.weight), `${m.share}%`, String(m.floor)])}
            />
            <p className="mt-2 text-xs" style={{ color: 'var(--metrics-soft)' }}>
              Total weight {data.total_weight}.
            </p>
          </Panel>
          {data.metrics.map((m) => (
            <Panel key={m.metric} title={`${m.metric} brackets (weight ${m.weight})`} testId={`score-brackets-${m.metric.replace(/\s+/g, '-').toLowerCase()}`}>
              <Table
                head={[m.by_days_worked ? 'Days worked' : 'Value', 'Brackets, highest first', `Below the last: floor ${m.floor}`]}
                rows={Object.entries(m.tables).map(([days, table]) => [days === 'any' ? 'Any week' : `${days} ${days === '1' ? 'day' : 'days'}`, table.map(([t, s]) => bracketText(t, s)).join('  ·  '), String(m.floor)])}
              />
            </Panel>
          ))}
          <Panel title="Grades" testId="score-grades">
            <Table head={['Grade', 'Average score']} rows={data.grades.map((g) => [g.grade, g.from > 0 ? `${g.from} or more` : 'below 1'])} />
          </Panel>
          {example && (
            <Panel title="A worked example" testId="score-example">
              <Table head={['Measure', 'Score', 'Weight', 'Score × weight']} rows={example.rows.map((r) => [r.metric, String(r.score), String(r.weight), String(r.points)])} />
              <p className="mt-2 text-sm">
                Sum of score × weight divided by the total weight = <strong>{example.total}</strong>.
              </p>
            </Panel>
          )}
        </div>
      )}
    </Page>
  );
}
