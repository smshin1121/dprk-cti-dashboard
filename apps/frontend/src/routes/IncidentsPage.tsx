/**
 * /incidents — protected list.
 *
 * Shell-level placeholder for Group B. Group F wires the live
 * /api/v1/incidents list with keyset cursor + country/sector/motivation
 * filters.
 */

export function IncidentsPage(): JSX.Element {
  return (
    <section
      data-testid="incidents-page"
      className="p-6"
      aria-labelledby="incidents-heading"
    >
      <h1 id="incidents-heading" className="text-2xl font-bold">
        Incidents
      </h1>
      <p className="mt-2 text-sm text-slate-600">
        Live list lands in Group F.
      </p>
    </section>
  )
}
