/**
 * Dev-only floating overlay for PR #25 Step 1 preset comparison.
 *
 * Fixed to bottom-right, switches between `default / sentry / wired /
 * linear` via `usePresetStore`. Non-invasive: it does not mount in
 * prod builds because the Shell gates it behind
 * `import.meta.env.DEV`. Stays intentionally ugly (visible at a
 * glance, obviously dev-tool) so it can't be mistaken for a
 * production affordance.
 *
 * Deleted when PR #25 Group A commits the winning preset's tokens.
 */
import type { DesignPreset } from '../stores/preset'
import { DESIGN_PRESETS, usePresetStore } from '../stores/preset'
import '../styles/presets/sentry.css'
import '../styles/presets/wired.css'
import '../styles/presets/linear.css'

const LABELS: Record<DesignPreset, string> = {
  default: 'Default (current)',
  sentry: 'Sentry (purple, ops)',
  wired: 'WIRED (newsprint)',
  linear: 'Linear (indigo)',
}

export function DesignPresetOverlay(): JSX.Element {
  const preset = usePresetStore((s) => s.preset)
  const setPreset = usePresetStore((s) => s.setPreset)

  return (
    <aside
      data-testid="design-preset-overlay"
      className="fixed bottom-4 right-4 z-[9999] rounded-md border border-yellow-400 bg-black/90 p-3 text-xs font-mono text-yellow-100 shadow-2xl"
      aria-label="PR #25 Step 1 preset picker (dev only)"
    >
      <div className="mb-2 font-bold uppercase tracking-widest text-yellow-300">
        PR #25 Step 1 preset
      </div>
      <div className="flex flex-col gap-1">
        {DESIGN_PRESETS.map((p) => (
          <label key={p} className="flex cursor-pointer items-center gap-2">
            <input
              type="radio"
              name="dprk-design-preset"
              value={p}
              checked={preset === p}
              onChange={() => setPreset(p)}
              className="cursor-pointer"
            />
            <span>{LABELS[p]}</span>
          </label>
        ))}
      </div>
      <p className="mt-2 max-w-[14rem] text-[10px] leading-tight text-yellow-200/70">
        Dev overlay. Hot-reload each value to compare. Winner lands in
        tokens.css then this overlay + stores/preset.ts are deleted.
      </p>
    </aside>
  )
}
