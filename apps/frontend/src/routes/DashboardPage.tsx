/**
 * /dashboard — protected landing.
 *
 * Group E wires the KPI strip (live /dashboard/summary). PR #13
 * adds areas [C]-[F] (world map, ATT&CK, etc.) below the strip.
 */

import { KPIStrip } from '../features/dashboard/KPIStrip'

export function DashboardPage(): JSX.Element {
  return (
    <section
      data-testid="dashboard-page"
      aria-labelledby="dashboard-heading"
      className="flex flex-col"
    >
      <h1 id="dashboard-heading" className="sr-only">
        Dashboard
      </h1>
      <KPIStrip />
    </section>
  )
}
