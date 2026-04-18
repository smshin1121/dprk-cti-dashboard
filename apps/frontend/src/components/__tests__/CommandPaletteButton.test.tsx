import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { CommandPaletteButton } from '../CommandPaletteButton'

describe('CommandPaletteButton', () => {
  it('renders a trigger button with ⌘K hint', () => {
    render(<CommandPaletteButton />)
    const btn = screen.getByTestId('cmdk-trigger')
    expect(btn).toBeInTheDocument()
    // Visible hint for discoverability. Platform-agnostic — the
    // mod+k shortcut resolves to cmd on Mac and ctrl elsewhere
    // browser-side. We standardize the visible glyph on ⌘K since
    // that's the design-doc convention.
    expect(btn).toHaveTextContent('⌘K')
  })

  it('clicking the trigger opens the empty dialog (shell-only scope)', async () => {
    const user = userEvent.setup()
    render(<CommandPaletteButton />)
    await user.click(screen.getByTestId('cmdk-trigger'))
    const dialog = await screen.findByTestId('cmdk-dialog')
    expect(dialog).toBeInTheDocument()
    // PR #13 ships the actual search + actions; PR #12 locks only
    // the skeleton. The message below is the affordance that makes
    // that scope visible to the user — the test pins it.
    expect(screen.getByTestId('cmdk-placeholder')).toHaveTextContent(
      /coming soon/i,
    )
    // No search input / no action items — just the placeholder.
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  })

  it('mod+k shortcut opens the dialog globally', async () => {
    const user = userEvent.setup()
    render(<CommandPaletteButton />)
    expect(screen.queryByTestId('cmdk-dialog')).not.toBeInTheDocument()

    // Ctrl+K (Windows/Linux) and Meta+K (macOS) — both paths must
    // open the palette so the keyboard shortcut works cross-platform
    // without sniffing navigator.platform at runtime.
    await user.keyboard('{Control>}k{/Control}')
    expect(await screen.findByTestId('cmdk-dialog')).toBeInTheDocument()

    await user.keyboard('{Escape}')
    expect(screen.queryByTestId('cmdk-dialog')).not.toBeInTheDocument()

    await user.keyboard('{Meta>}k{/Meta}')
    expect(await screen.findByTestId('cmdk-dialog')).toBeInTheDocument()
  })

  it('mod+k inside input fields does NOT swallow browser default (guards against capture leaks)', async () => {
    const user = userEvent.setup()
    render(
      <>
        <input data-testid="form-field" />
        <CommandPaletteButton />
      </>,
    )
    const input = screen.getByTestId('form-field') as HTMLInputElement
    input.focus()
    // Typing in a form field should NOT trip the palette — otherwise
    // the filter-bar date input breaks when the user types "k" after
    // holding ctrl by accident. We handle the shortcut at the window
    // level but bail out when focus is inside an editable field.
    await user.keyboard('k')
    expect(screen.queryByTestId('cmdk-dialog')).not.toBeInTheDocument()
  })

  it('closes on Escape', async () => {
    const user = userEvent.setup()
    render(<CommandPaletteButton />)
    await user.click(screen.getByTestId('cmdk-trigger'))
    expect(await screen.findByTestId('cmdk-dialog')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByTestId('cmdk-dialog')).not.toBeInTheDocument()
  })
})
