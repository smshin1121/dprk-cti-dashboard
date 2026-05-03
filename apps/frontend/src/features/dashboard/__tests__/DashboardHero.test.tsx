/**
 * DashboardHero unit test — Ferrari L4 vocabulary pin (commit 9).
 *
 * Covers the four observable states + the Ferrari spec-cell vocabulary
 * pins (number-display 80px / -1.6px tracking / Rosso Corsa value;
 * button-primary + button-outline-on-dark CTAs; caption-uppercase
 * label; display-md sub-headline).
 *
 * No network — useDashboardSummary is mocked through a tiny shim
 * pattern matching other dashboard widget tests (KPICard, etc.).
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { DashboardHero } from '../DashboardHero'

function buildHarness(): {
  Wrapper: ({ children }: { children: ReactNode }) => JSX.Element
} {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  function Wrapper({ children }: { children: ReactNode }): JSX.Element {
    return (
      <MemoryRouter>
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      </MemoryRouter>
    )
  }
  return { Wrapper }
}

describe('DashboardHero', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('renders the loading placeholder dash + aria-busy=true', () => {
    const fetchMock = vi.fn(() => new Promise(() => {})) // never resolves
    vi.stubGlobal('fetch', fetchMock)
    const { Wrapper } = buildHarness()
    render(
      <Wrapper>
        <DashboardHero />
      </Wrapper>,
    )

    const value = screen.getByTestId('dashboard-hero-value')
    expect(value).toHaveTextContent('—')
    expect(value.getAttribute('aria-busy')).toBe('true')
    // Number-display vocabulary pinned even in loading state so the
    // spec-cell footprint stays reserved while data is in flight.
    expect(value.className).toMatch(/(?:^|\s)text-\[80px\](?:\s|$)/)
    expect(value.className).toMatch(/\btracking-number-display\b/)
    expect(value.className).toMatch(/\bfont-cta\b/)
  })

  it('renders the populated number in Rosso Corsa (text-signal)', async () => {
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({
          total_reports: 42,
          total_incidents: 1234,
          total_actors: 7,
          reports_by_year: [],
          incidents_by_motivation: [],
          top_groups: [],
          top_sectors: [],
          top_sources: [],
        }),
        { status: 200, headers: { 'content-type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    const { Wrapper } = buildHarness()
    render(
      <Wrapper>
        <DashboardHero />
      </Wrapper>,
    )

    // Wait for the populated number to land + verify the ink color
    // is Rosso Corsa-bound (text-signal aliases through to --primary).
    const value = await screen.findByTestId('dashboard-hero-value')
    await vi.waitFor(() => {
      expect(value.textContent).toBe('1,234')
    })
    expect(value.getAttribute('aria-busy')).toBe('false')
    expect(value.className).toMatch(/\btext-signal\b/)
    // Number-display geometry pinned across loading + populated.
    expect(value.className).toMatch(/(?:^|\s)text-\[80px\](?:\s|$)/)
    expect(value.className).toMatch(/\btracking-number-display\b/)
    expect(value.className).toMatch(/\bfont-cta\b/)
  })

  it('pins button-primary vocabulary on the primary CTA', () => {
    const { Wrapper } = buildHarness()
    render(
      <Wrapper>
        <DashboardHero />
      </Wrapper>,
    )
    const primary = screen.getByTestId('dashboard-hero-cta-primary')
    expect(primary.getAttribute('href')).toBe('/incidents')
    // Ferrari button-primary vocabulary: bg-primary, sharp 0px, h-12,
    // uppercase tracking-cta, font-cta. Pin the load-bearing classes.
    expect(primary.className).toMatch(/\bbg-primary\b/)
    expect(primary.className).toMatch(/\brounded-none\b/)
    expect(primary.className).toMatch(/\bh-12\b/)
    expect(primary.className).toMatch(/\btracking-cta\b/)
    expect(primary.className).toMatch(/\buppercase\b/)
    expect(primary.className).toMatch(/\bfont-cta\b/)
  })

  it('pins button-outline-on-dark vocabulary on the outline CTA', () => {
    const { Wrapper } = buildHarness()
    render(
      <Wrapper>
        <DashboardHero />
      </Wrapper>,
    )
    const outline = screen.getByTestId('dashboard-hero-cta-outline')
    expect(outline.getAttribute('href')).toBe('/reports')
    // Ferrari button-outline-on-dark vocabulary: transparent bg, 1px
    // ink border, sharp 0px, uppercase tracking-cta, font-cta.
    expect(outline.className).toMatch(/\bbg-transparent\b/)
    expect(outline.className).toMatch(/\bborder-ink\b/)
    expect(outline.className).toMatch(/\brounded-none\b/)
    expect(outline.className).toMatch(/\btracking-cta\b/)
    expect(outline.className).toMatch(/\buppercase\b/)
    expect(outline.className).toMatch(/\bfont-cta\b/)
    // Negative guard — outline must NOT carry bg-primary.
    expect(outline.className).not.toMatch(/\bbg-primary\b/)
  })

  it('pins caption-uppercase vocabulary on the hero label', () => {
    const { Wrapper } = buildHarness()
    render(
      <Wrapper>
        <DashboardHero />
      </Wrapper>,
    )
    const label = screen.getByTestId('dashboard-hero-label')
    // caption-uppercase per DESIGN.md typography: font-cta uppercase
    // tracking-caption + text-[10px].
    expect(label.className).toMatch(/\btracking-caption\b/)
    expect(label.className).toMatch(/\buppercase\b/)
    expect(label.className).toMatch(/\bfont-cta\b/)
    expect(label.className).toMatch(/(?:^|\s)text-\[10px\](?:\s|$)/)
  })

  it('pins display-md vocabulary on the sub-headline', () => {
    const { Wrapper } = buildHarness()
    render(
      <Wrapper>
        <DashboardHero />
      </Wrapper>,
    )
    const sub = screen.getByTestId('dashboard-hero-subheading')
    // display-md per DESIGN.md typography.display-md: font-display
    // (500) NEVER bold + tracking-display + text-2xl (24px on the
    // Tailwind ladder — closest to display-md 26px without an
    // arbitrary-value class).
    expect(sub.className).toMatch(/\bfont-display\b/)
    expect(sub.className).toMatch(/\btracking-display\b/)
    expect(sub.className).toMatch(/\btext-2xl\b/)
    // Negative guard — Ferrari display NEVER bold.
    expect(sub.className).not.toMatch(/\bfont-bold\b/)
    expect(sub.className).not.toMatch(/\bfont-semibold\b/)
  })
})
