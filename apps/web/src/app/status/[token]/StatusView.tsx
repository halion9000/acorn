import type { ClientStatusPage } from '../../../lib/client-status';

/** Draws the client's page from what the API sent. Nothing is added here: the wording is the API's (`copy`), the numbers are its numbers. */
export function StatusView({ page }: { page: ClientStatusPage }) {
  const { copy } = page;
  const meter = (label: string, m: { total: number; protected: number; percent: number | null } | null, testId: string) => (
    <div className="rounded-lg border border-gray-200 bg-white p-4" data-testid={testId}>
      <div className="text-sm text-gray-600">{label}</div>
      {m === null || m.percent === null ? (
        <div className="mt-1 text-lg text-gray-500">Not available yet</div>
      ) : (
        <>
          <div className="mt-1 text-3xl font-semibold text-gray-900">{m.percent}%</div>
          <div className="text-sm text-gray-500">{m.protected} of {m.total}</div>
        </>
      )}
    </div>
  );
  return (
    <main className="mx-auto max-w-2xl px-4 py-10 text-gray-900">
      <h1 className="text-2xl font-semibold">{copy.title}</h1>
      {page.client_name ? <p className="mt-1 text-lg text-gray-700">{page.client_name}</p> : null}
      <p className="mt-3 text-sm text-gray-600">{copy.intro}</p>
      <div className="mt-6 grid gap-3 sm:grid-cols-2">
        {meter(copy.devices, page.devices, 'status-devices')}
        {meter(copy.people, page.people, 'status-people')}
        <div className="rounded-lg border border-gray-200 bg-white p-4 sm:col-span-2" data-testid="status-alerts">
          <div className="text-sm text-gray-600">{copy.alerts_open}</div>
          <div className="mt-1 text-3xl font-semibold text-gray-900">{page.alerts.open}</div>
          {page.alerts.open > 0 ? <div className="text-sm text-gray-500">{page.alerts.being_worked_on} {copy.alerts_handled}</div> : null}
        </div>
      </div>
      {page.tools.length > 0 ? (
        <section className="mt-6" data-testid="status-tools">
          <h2 className="text-sm font-semibold text-gray-700">{copy.tools}</h2>
          <ul className="mt-2 list-disc pl-5 text-sm text-gray-700">
            {page.tools.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {page.generated_at ? <p className="mt-6 text-xs text-gray-400">Updated {new Date(page.generated_at).toUTCString()}</p> : null}
      <p className="mt-2 text-xs text-gray-500">{copy.footer}</p>
    </main>
  );
}
