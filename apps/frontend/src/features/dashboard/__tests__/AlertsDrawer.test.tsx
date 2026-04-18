import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { AlertsDrawer } from '../AlertsDrawer'

afterEach(() => vi.restoreAllMocks())

describe('AlertsDrawer — static shell', () => {
  it('renders trigger; panel is closed by default', () => {
    render(<AlertsDrawer />)
    expect(screen.getByTestId('alerts-drawer-trigger')).toBeInTheDocument()
    expect(screen.queryByTestId('alerts-drawer-panel')).not.toBeInTheDocument()
  })

  it('trigger click opens panel showing empty state + phase-4 note', async () => {
    const user = userEvent.setup()
    render(<AlertsDrawer />)
    await user.click(screen.getByTestId('alerts-drawer-trigger'))
    expect(screen.getByTestId('alerts-drawer-panel')).toBeInTheDocument()
    expect(screen.getByTestId('alerts-drawer-empty')).toBeInTheDocument()
    expect(screen.getByTestId('alerts-drawer-phase-note')).toBeInTheDocument()
  })

  it('close button closes the panel', async () => {
    const user = userEvent.setup()
    render(<AlertsDrawer />)
    await user.click(screen.getByTestId('alerts-drawer-trigger'))
    expect(screen.getByTestId('alerts-drawer-panel')).toBeInTheDocument()
    await user.click(screen.getByTestId('alerts-drawer-close'))
    expect(screen.queryByTestId('alerts-drawer-panel')).not.toBeInTheDocument()
  })

  it('Escape key closes the panel', async () => {
    const user = userEvent.setup()
    render(<AlertsDrawer />)
    await user.click(screen.getByTestId('alerts-drawer-trigger'))
    expect(screen.getByTestId('alerts-drawer-panel')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByTestId('alerts-drawer-panel')).not.toBeInTheDocument()
  })

  it('trigger ARIA reflects open/closed state', async () => {
    const user = userEvent.setup()
    render(<AlertsDrawer />)
    const trigger = screen.getByTestId('alerts-drawer-trigger')
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    await user.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
  })

  it('is marked as a Phase 4 static shell via data attributes', () => {
    render(<AlertsDrawer />)
    const root = screen.getByTestId('alerts-drawer-root')
    expect(root).toHaveAttribute('data-phase-status', 'static-shell')
    expect(root).toHaveAttribute('data-phase', 'phase-4')
  })

  it('fires ZERO fetches across mount + open + close cycle (no data plumbing)', async () => {
    const spy = vi.spyOn(global, 'fetch')
    const user = userEvent.setup()
    render(<AlertsDrawer />)
    await user.click(screen.getByTestId('alerts-drawer-trigger'))
    await user.click(screen.getByTestId('alerts-drawer-close'))
    // Give any queued microtasks a chance to fire.
    await waitFor(() => expect(true).toBe(true))
    expect(spy).not.toHaveBeenCalled()
  })
})
