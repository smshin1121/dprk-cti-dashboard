import type { Config } from 'tailwindcss'
import animate from 'tailwindcss-animate'

export default {
  // Ferrari L1: theme model collapsed from light/dark/system to a
  // single dark canvas (#181818). Per-section light editorial bands
  // are opt-in via the `.editorial-band-light` class declared in
  // styles/tokens.css — Tailwind dark: variants are no longer used
  // and the darkMode selector has been removed.
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
      // Ferrari sharp 0px corners are the brand button shape. The
      // `--radius` var collapses to 0 in tokens.css; pill geometry
      // (rounded-full = 9999px) is reserved for badges only; form
      // inputs opt in to a 4px corner via the `rounded-input` alias.
      borderRadius: {
        DEFAULT: 'var(--radius)',
        lg: 'var(--radius)',
        md: 'var(--radius)',
        sm: 'var(--radius)',
        input: 'var(--radius-input)',
      },
      // Ferrari named 8px spacing ladder — supplements (does not
      // replace) the Tailwind default scale so existing `p-4` etc.
      // keep working until L2 sweep migrates them.
      spacing: {
        xxxs: '4px',
        xxs: '8px',
        xs: '16px',
        sm: '24px',
        md: '32px',
        lg: '48px',
        xl: '64px',
        xxl: '96px',
        super: '128px',
      },
      fontFamily: {
        // Inter Variable substitutes FerrariSans (licensed). All
        // weights resolved via the variable axis from
        // @fontsource-variable/inter (loaded in src/main.tsx).
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
      // Ferrari weight semantics — display NEVER bold (500), CTAs
      // bold (700), body 400. Aliases keep usage explicit at call
      // sites and prevent accidental `font-bold` on display copy.
      fontWeight: {
        display: '500',
        body: '400',
        cta: '700',
      },
      // Ferrari letter-spacing ladder.
      letterSpacing: {
        // -1% on display sizes; CSS `em` so it scales with font size.
        display: '-0.01em',
        // 1.4px tracking on uppercase CTAs at 14px base = ~0.0875em.
        cta: '0.0875em',
        // 0.65px tracking on uppercase nav at 13px base = ~0.05em.
        nav: '0.05em',
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
