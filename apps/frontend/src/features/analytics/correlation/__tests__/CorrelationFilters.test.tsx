/**
 * Plan PR-C T2 — Q1 catalog dropdown grouping (C6 lock).
 *
 * Asserts that each SeriesPicker (X / Y axis) renders the open
 * dropdown with two section headers — `[ Reports ]` and
 * `[ Incidents ]` — and the catalog options nested under the header
 * matching their schema `root` field (`apps/frontend/src/lib/api/schemas.ts:692`).
 * `id` is OPAQUE per umbrella §2.2 — grouping MUST key on `root`,
 * not on any prefix of `id`.
 *
 * Locale pin — per memory `pattern_i18n_pin_in_test_locale`:
 * happy-dom navigator default differs across runs and i18n state can
 * leak across `__tests__` files when modules are cached, so this file
 * imports the bootstrap and changes language synchronously in
 * `beforeEach`. Without the pin, asserting "Reports" / "Incidents"
 * literal copy is non-deterministic.
 *
 * Existing per-option testids (`correlation-filter-{x|y}-option-{id}`)
 * are preserved unchanged — section headers wrap them, do not replace
 * them. The third test case pins this regression guard.
 */

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import '../../../../i18n'
import { i18n } from '../../../../i18n'
import type { CorrelationSeriesItem } from '../../../../lib/api/schemas'
import { CorrelationFilters } from '../CorrelationFilters'

// Discriminating fixture per Codex T2 r1 fold. Two of the four items
// have an `id` whose lexical prefix DISAGREES with their `root` (the
// "shadow" rows — `incidents.legacyReportFamily` is rooted at
// reports.published, and `reports.legacyIncidentFamily` is rooted at
// incidents.reported). A faulty `id.startsWith('reports.')` grouping
// would put these in the wrong header; a correct `s.root` grouping
// puts them where the schema says. Per umbrella §2.2, `id` is OPAQUE —
// the FE may NOT parse its structure, so this discriminating shape is
// a real-world possibility, not a synthetic edge case.
const CATALOG: CorrelationSeriesItem[] = [
  {
    id: 'reports.total',
    label_ko: '보고서 총수',
    label_en: 'Total reports',
    root: 'reports.published',
    bucket: 'monthly',
  },
  {
    id: 'incidents.legacyReportFamily',
    label_ko: '구식 보고서 계열',
    label_en: 'Legacy report family',
    root: 'reports.published',
    bucket: 'monthly',
  },
  {
    id: 'incidents.total',
    label_ko: '사건 총수',
    label_en: 'Total incidents',
    root: 'incidents.reported',
    bucket: 'monthly',
  },
  {
    id: 'reports.legacyIncidentFamily',
    label_ko: '구식 사건 계열',
    label_en: 'Legacy incident family',
    root: 'incidents.reported',
    bucket: 'monthly',
  },
]

function renderFilters(overrides: Partial<Parameters<typeof CorrelationFilters>[0]> = {}) {
  const props = {
    catalog: CATALOG,
    x: 'reports.total',
    y: 'incidents.total',
    dateFrom: null,
    dateTo: null,
    onChangeX: vi.fn(),
    onChangeY: vi.fn(),
    onChangeDateFrom: vi.fn(),
    onChangeDateTo: vi.fn(),
    ...overrides,
  }
  return render(<CorrelationFilters {...props} />)
}

beforeEach(async () => {
  await i18n.changeLanguage('en')
})

describe('CorrelationFilters — Q1 catalog grouping (C6 lock)', () => {
  it('renders Reports + Incidents section headers in the X picker dropdown', async () => {
    const user = userEvent.setup()
    renderFilters()

    await user.click(screen.getByTestId('correlation-filter-x'))

    const reportsHeader = screen.getByTestId('correlation-filter-x-group-reports')
    const incidentsHeader = screen.getByTestId('correlation-filter-x-group-incidents')

    expect(reportsHeader).toBeVisible()
    expect(reportsHeader).toHaveTextContent(/^Reports$/)
    expect(incidentsHeader).toBeVisible()
    expect(incidentsHeader).toHaveTextContent(/^Incidents$/)
  })

  it('nests options under the header matching their schema root field (NOT id prefix)', async () => {
    const user = userEvent.setup()
    renderFilters()

    await user.click(screen.getByTestId('correlation-filter-y'))

    const reportsGroup = screen.getByTestId('correlation-filter-y-group-reports-list')
    const incidentsGroup = screen.getByTestId('correlation-filter-y-group-incidents-list')

    // Items with root === 'reports.published' MUST nest under the Reports
    // header — including the shadow row whose `id` starts with "incidents."
    // (an `id.startsWith('reports.')` heuristic would mis-group it).
    expect(within(reportsGroup).getByTestId('correlation-filter-y-option-reports.total')).toBeInTheDocument()
    expect(
      within(reportsGroup).getByTestId('correlation-filter-y-option-incidents.legacyReportFamily'),
    ).toBeInTheDocument()

    // Items with root === 'incidents.reported' MUST nest under the Incidents
    // header — including the shadow row whose `id` starts with "reports.".
    expect(
      within(incidentsGroup).getByTestId('correlation-filter-y-option-incidents.total'),
    ).toBeInTheDocument()
    expect(
      within(incidentsGroup).getByTestId('correlation-filter-y-option-reports.legacyIncidentFamily'),
    ).toBeInTheDocument()

    // Discrimination: an id-prefix grouping would put the shadow rows
    // in the OPPOSITE group. Pin both negatives.
    expect(
      within(reportsGroup).queryByTestId('correlation-filter-y-option-incidents.total'),
    ).toBeNull()
    expect(
      within(reportsGroup).queryByTestId('correlation-filter-y-option-reports.legacyIncidentFamily'),
    ).toBeNull()
    expect(
      within(incidentsGroup).queryByTestId('correlation-filter-y-option-reports.total'),
    ).toBeNull()
    expect(
      within(incidentsGroup).queryByTestId('correlation-filter-y-option-incidents.legacyReportFamily'),
    ).toBeNull()
  })

  it('preserves per-option testids and click-to-pick behavior unchanged (regression guard)', async () => {
    const user = userEvent.setup()
    const onChangeX = vi.fn()
    renderFilters({ onChangeX })

    await user.click(screen.getByTestId('correlation-filter-x'))
    await user.click(screen.getByTestId('correlation-filter-x-option-incidents.total'))

    expect(onChangeX).toHaveBeenCalledTimes(1)
    expect(onChangeX).toHaveBeenCalledWith('incidents.total')
  })
})
