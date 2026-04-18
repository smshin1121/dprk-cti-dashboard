/**
 * Route-level loading skeleton (plan D11 lock).
 *
 * Rendered inside the protected-route outlet while `useAuth()` is
 * still in 'loading' state or a route-level lazy chunk is resolving.
 * Kept deliberately minimal — two pulse-animated bars — so it does
 * not imply any specific content shape and therefore does not mis-hint
 * at what will appear once the data arrives.
 *
 * NOT a global blocking spinner. The Shell around this is already
 * rendered (nav stays visible); only the main content area
 * shows a placeholder. D11 explicitly rules out full-screen blocking
 * overlays because they mask partial progress and hide that the nav
 * is actually interactive during the wait.
 *
 * Data-testid attached so route-mount tests can assert the skeleton
 * path without coupling to visual markup.
 */

export function RouteSkeleton(): JSX.Element {
  return (
    <div
      data-testid="route-skeleton"
      className="flex flex-col gap-3 p-6"
      aria-live="polite"
      aria-busy="true"
    >
      <div className="h-6 w-48 animate-pulse rounded bg-border-card" />
      <div className="h-4 w-80 animate-pulse rounded bg-border-card" />
    </div>
  )
}
