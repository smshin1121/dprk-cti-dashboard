/**
 * /actors — protected list.
 *
 * Shell-level placeholder for Group B. Group F wires the live
 * /api/v1/actors list endpoint with pagination.
 */

export function ActorsPage(): JSX.Element {
  return (
    <section
      data-testid="actors-page"
      className="p-6"
      aria-labelledby="actors-heading"
    >
      <h1 id="actors-heading" className="text-2xl font-bold">
        Actors
      </h1>
      <p className="mt-2 text-sm text-slate-600">
        Live list lands in Group F.
      </p>
    </section>
  )
}
