/**
 * Plan §B8 (e) — warning-chip render for each of the 6 codes
 * (umbrella §5.2 + CONTRACT.md §2 `CorrelationWarningCode` enum).
 *
 * RED state at T7. T9 implements `CorrelationWarningChips` rendering
 * one chip per `interpretation.warnings[]` entry, each chip's copy
 * keyed by `correlation.warnings.<code>` in i18n (T11). Until then
 * tests fail at runtime with the stub `NotImplementedError`.
 *
 * Test discipline: assert one chip per code via a per-code data-testid
 * (`warning-chip-<code>`); the renderer's rule is one chip per
 * warnings[] entry (no de-dupe, since the BE never emits duplicates
 * within a single response per spec).
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { CorrelationWarningChips } from '../CorrelationWarningChips'
import type { CorrelationWarning, CorrelationWarningCode } from '../../../../lib/api/schemas'

const ALL_CODES: CorrelationWarningCode[] = [
  'non_stationary_suspected',
  'outlier_influence',
  'sparse_window',
  'cross_rooted_pair',
  'identity_or_containment_suspected',
  'low_count_suppressed_cells',
]

function warning(code: CorrelationWarningCode): CorrelationWarning {
  return {
    code,
    message: `Stub message for ${code}`,
    severity: code === 'non_stationary_suspected' ? 'warn' : 'info',
  }
}

describe('CorrelationWarningChips — every code renders (Plan §B8 e)', () => {
  it('renders nothing when warnings is empty', () => {
    const { container } = render(<CorrelationWarningChips warnings={[]} />)
    expect(container.querySelector('[data-testid^="warning-chip-"]')).toBeNull()
  })

  it.each(ALL_CODES)('renders a chip for %s', (code) => {
    render(<CorrelationWarningChips warnings={[warning(code)]} />)
    expect(screen.getByTestId(`warning-chip-${code}`)).toBeVisible()
  })

  it('renders one chip per entry across all 6 codes when all present', () => {
    render(<CorrelationWarningChips warnings={ALL_CODES.map(warning)} />)
    for (const code of ALL_CODES) {
      expect(screen.getByTestId(`warning-chip-${code}`)).toBeVisible()
    }
  })

  it('distinguishes severity via a per-chip data attribute (info vs warn)', () => {
    render(
      <CorrelationWarningChips
        warnings={[
          warning('sparse_window'), // info
          warning('non_stationary_suspected'), // warn
        ]}
      />,
    )
    expect(
      screen.getByTestId('warning-chip-sparse_window').getAttribute('data-severity'),
    ).toBe('info')
    expect(
      screen.getByTestId('warning-chip-non_stationary_suspected').getAttribute('data-severity'),
    ).toBe('warn')
  })
})
