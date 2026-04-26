import type { Config } from 'tailwindcss'
import animate from 'tailwindcss-animate'

export default {
  // Plan D4: switch via html[data-theme="dark"] attribute (not the
  // .dark class). Tailwind 3.4+ `['selector', <css-selector>]` form
  // selects dark styles when the given selector matches the html
  // element. The 'system' branch is handled inside tokens.css via
  // `@media (prefers-color-scheme: dark)` so Tailwind's dark:*
  // utilities fire there too.
  darkMode: ['selector', '[data-theme="dark"], [data-theme="system"]:is(:root)'],
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    container: {
      center: true,
      padding: '2rem',
      screens: {
        '2xl': '1400px',
      },
    },
    extend: {
      colors: {
        // Semantic surface + text tokens (plan D4 lock). All HSL
        // triples backed by CSS vars in styles/tokens.css — flip
        // automatically between light / dark / system.
        app: 'hsl(var(--app-bg))',
        surface: {
          DEFAULT: 'hsl(var(--surface))',
          elevated: 'hsl(var(--surface-elevated))',
        },
        ink: {
          DEFAULT: 'hsl(var(--ink))',
          muted: 'hsl(var(--ink-muted))',
          subtle: 'hsl(var(--ink-subtle))',
        },
        signal: {
          DEFAULT: 'hsl(var(--signal))',
          hover: 'hsl(var(--signal-hover))',
          fg: 'hsl(var(--signal-fg))',
        },
        status: {
          crit: 'hsl(var(--status-crit))',
          warn: 'hsl(var(--status-warn))',
          elev: 'hsl(var(--status-elev))',
          ok: 'hsl(var(--status-ok))',
          info: 'hsl(var(--status-info))',
          special: 'hsl(var(--status-special))',
        },
        grid: 'hsl(var(--grid))',

        // Border tokens — `border` keyword is reserved by Tailwind's
        // default theme, so the semantic strong/card tokens sit
        // alongside the shadcn `border` default below.
        'border-card': 'hsl(var(--border-card))',
        'border-strong': 'hsl(var(--border-strong))',

        // shadcn compatibility tokens (unchanged).
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        popover: {
          DEFAULT: 'hsl(var(--popover))',
          foreground: 'hsl(var(--popover-foreground))',
        },
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      fontFamily: {
        sans: [
          'Inter Variable',
          'Inter',
          'Segoe UI',
          'ui-sans-serif',
          'system-ui',
          'sans-serif',
        ],
        mono: [
          'JetBrains Mono',
          'Geist Mono',
          'ui-monospace',
          'SFMono-Regular',
          'monospace',
        ],
      },
      keyframes: {
        'accordion-down': {
          from: { height: '0' },
          to: { height: 'var(--radix-accordion-content-height)' },
        },
        'accordion-up': {
          from: { height: 'var(--radix-accordion-content-height)' },
          to: { height: '0' },
        },
      },
      animation: {
        'accordion-down': 'accordion-down 0.2s ease-out',
        'accordion-up': 'accordion-up 0.2s ease-out',
      },
    },
  },
  plugins: [animate],
} satisfies Config
