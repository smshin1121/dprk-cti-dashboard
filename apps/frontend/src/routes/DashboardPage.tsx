/**
 * /dashboard — protected landing.
 *
 * Shell-level placeholder for PR #12 Group B. Group E wires in the
 * KPI strip + live /dashboard/summary. PR #13 adds areas [C]-[F]
 * (world map, ATT&CK, etc.).
 */

export function DashboardPage(): JSX.Element {
  return (
    <section
      data-testid="dashboard-page"
      className="p-6"
      aria-labelledby="dashboard-heading"
    >
      <h1 id="dashboard-heading" className="text-2xl font-bold">
        Dashboard
      </h1>
      <p className="mt-2 text-sm text-slate-600">
        KPI strip wires in Group E. Dashboard visualizations arrive in PR #13.
      </p>
    </section>
  )
}
