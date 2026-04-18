/**
 * /reports — protected list.
 *
 * Shell-level placeholder for Group B. Group F wires the live
 * /api/v1/reports list with keyset cursor pagination + filters.
 */

export function ReportsPage(): JSX.Element {
  return (
    <section
      data-testid="reports-page"
      className="p-6"
      aria-labelledby="reports-heading"
    >
      <h1 id="reports-heading" className="text-2xl font-bold">
        Reports
      </h1>
      <p className="mt-2 text-sm text-slate-600">
        Live list lands in Group F.
      </p>
    </section>
  )
}
