#!/usr/bin/env node
/**
 * PR #13 Group K — Lighthouse manual audit harness (plan D6).
 *
 * Scope:
 *   - Runs Lighthouse N times against the Vite **preview** build
 *     (default http://127.0.0.1:4173) — NOT the dev server. D6
 *     locks the audit on the production-shaped bundle.
 *   - Collects 4 categories per run (performance / accessibility /
 *     best-practices / seo) across 2 theme variants (light / dark),
 *     emulated via Chrome DevTools Protocol
 *     `Emulation.setEmulatedMedia` with `prefers-color-scheme` —
 *     the FOUC script in `index.html` respects this before the
 *     React root hydrates.
 *   - Writes per-run JSON (full LH report) + a SUMMARY.md with
 *     3-run medians to `apps/frontend/lighthouse/reports/`.
 *   - **Never exits non-zero on score.** D6 explicit: "NOT a CI
 *     hard gate." The harness is purely informational; the PR
 *     reviewer reads the median table and decides acceptance.
 *
 * Usage:
 *   pnpm run lighthouse:audit
 *
 * Env overrides:
 *   LH_URL_BASE   — preview origin (default http://127.0.0.1:4173)
 *   LH_PATH       — target path (default /dashboard)
 *   LH_RUNS       — runs per theme (default 3 — median window)
 *   LH_THEMES     — comma list (default "light,dark")
 *   LH_TIMEOUT_MS — per-run ceiling (default 90000)
 *
 * Prerequisites (documented in lighthouse/README.md):
 *   1. `pnpm run build`
 *   2. `pnpm run preview` (another terminal — blocks on 4173)
 *   3. BE running on :8000 AND a seeded session cookie already
 *      forwarded to the preview origin — otherwise /dashboard
 *      redirects to /login and the audit will measure /login.
 *
 * Why programmatic (not the `lighthouse` CLI):
 *   Theme emulation needs CDP before navigation. The CLI exposes
 *   only a limited set of screenEmulation knobs and doesn't carry
 *   `prefers-color-scheme`. The programmatic API lets us drive
 *   `Emulation.setEmulatedMedia` on the Chrome target directly via
 *   chrome-launcher + a fresh LH runner per theme.
 */

import { launch as chromeLauncherLaunch } from 'chrome-launcher'
import lighthouse from 'lighthouse'
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const REPORTS_DIR = path.resolve(__dirname, 'reports')

const URL_BASE = process.env.LH_URL_BASE ?? 'http://127.0.0.1:4173'
const TARGET_PATH = process.env.LH_PATH ?? '/dashboard'
const RUNS = Number.parseInt(process.env.LH_RUNS ?? '3', 10)
const THEMES = (process.env.LH_THEMES ?? 'light,dark').split(',').map((s) => s.trim())
const RUN_TIMEOUT_MS = Number.parseInt(process.env.LH_TIMEOUT_MS ?? '90000', 10)

const CATEGORIES = ['performance', 'accessibility', 'best-practices', 'seo']

/** @typedef {{ performance: number, accessibility: number, 'best-practices': number, seo: number }} CategoryScores */

/**
 * Drive a single Lighthouse run against a fresh headless Chrome
 * with the requested theme emulated at the CDP layer before
 * navigation.
 *
 * @param {string} targetUrl
 * @param {'light' | 'dark'} theme
 * @returns {Promise<{ scores: CategoryScores, lhr: unknown }>}
 */
async function runOnce(targetUrl, theme) {
  // Use an explicit per-run user-data dir — chrome-launcher's default
  // in `%TEMP%\lighthouse.<rand>` occasionally collides with stale
  // Chrome processes on Windows and throws EPERM. A fresh, script-
  // scoped dir avoids that class of failure and is torn down on exit.
  const userDataDir = await mkdtemp(
    path.join(os.tmpdir(), `dprk-cti-lh-${theme}-`),
  )
  const chrome = await chromeLauncherLaunch({
    chromeFlags: [
      '--headless=new',
      '--disable-gpu',
      '--no-sandbox',
      '--no-first-run',
      '--disable-default-apps',
      '--disable-extensions',
      `--user-data-dir=${userDataDir}`,
    ],
  })

  try {
    /** @type {import('lighthouse').Flags} */
    const flags = {
      logLevel: 'error',
      output: 'json',
      port: chrome.port,
      onlyCategories: CATEGORIES,
      maxWaitForLoad: RUN_TIMEOUT_MS,
    }

    /** @type {import('lighthouse').Config} */
    const config = {
      extends: 'lighthouse:default',
      settings: {
        // Desktop preset — D6 lock mentions /dashboard not mobile.
        formFactor: 'desktop',
        throttling: {
          rttMs: 40,
          throughputKbps: 10 * 1024,
          cpuSlowdownMultiplier: 1,
          requestLatencyMs: 0,
          downloadThroughputKbps: 0,
          uploadThroughputKbps: 0,
        },
        screenEmulation: {
          mobile: false,
          width: 1350,
          height: 940,
          deviceScaleFactor: 1,
          disabled: false,
        },
        emulatedUserAgent:
          'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ' +
          '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        // prefers-color-scheme emulation. `emulatedMediaFeatures` is
        // a Lighthouse setting that lighthouse passes through to
        // `Emulation.setEmulatedMedia` before the nav, so the FOUC
        // script reads the correct media query on first paint.
        emulatedMediaFeatures:
          theme === 'dark'
            ? [{ name: 'prefers-color-scheme', value: 'dark' }]
            : [{ name: 'prefers-color-scheme', value: 'light' }],
      },
    }

    const result = await lighthouse(targetUrl, flags, config)
    if (!result?.lhr) {
      throw new Error('Lighthouse returned no lhr payload')
    }
    const cats = result.lhr.categories
    const scores = /** @type {CategoryScores} */ ({
      performance: Math.round((cats.performance?.score ?? 0) * 100),
      accessibility: Math.round((cats.accessibility?.score ?? 0) * 100),
      'best-practices': Math.round((cats['best-practices']?.score ?? 0) * 100),
      seo: Math.round((cats.seo?.score ?? 0) * 100),
    })
    return { scores, lhr: result.lhr }
  } finally {
    try {
      await chrome.kill()
    } catch {
      // chrome.kill() can throw on Windows if the process already
      // exited — ignore; we still need to clean up the userDataDir.
    }
    // Best-effort cleanup; Chrome may still hold file locks for a
    // moment after kill(). Failure here is a leak, not a correctness
    // issue, so we swallow errors.
    try {
      await rm(userDataDir, { recursive: true, force: true })
    } catch {
      /* leak — logged by OS cleanup later */
    }
  }
}

/**
 * @param {number[]} values
 * @returns {number}
 */
function median(values) {
  if (values.length === 0) return 0
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 0
    ? Math.round((sorted[mid - 1] + sorted[mid]) / 2)
    : sorted[mid]
}

/**
 * @param {CategoryScores[]} runs
 * @returns {CategoryScores}
 */
function medianScores(runs) {
  return {
    performance: median(runs.map((r) => r.performance)),
    accessibility: median(runs.map((r) => r.accessibility)),
    'best-practices': median(runs.map((r) => r['best-practices'])),
    seo: median(runs.map((r) => r.seo)),
  }
}

/**
 * @param {string} theme
 * @param {CategoryScores[]} runs
 * @returns {string}
 */
function markdownRowsForTheme(theme, runs) {
  const med = medianScores(runs)
  const header = `### Theme: \`${theme}\`\n\n| Category | Run 1 | Run 2 | Run 3 | **Median** |\n|:---|---:|---:|---:|---:|`
  const cells = CATEGORIES.map((cat) => {
    const runCells = runs.map((r) => String(r[cat])).join(' | ')
    const medianCell = String(med[cat])
    const pad = Array.from({ length: Math.max(0, RUNS - runs.length) }, () => '—').join(' | ')
    return `| ${cat} | ${runCells}${pad ? ' | ' + pad : ''} | **${medianCell}** |`
  })
  return [header, ...cells].join('\n')
}

async function main() {
  await mkdir(REPORTS_DIR, { recursive: true })
  const targetUrl = URL_BASE + TARGET_PATH
  const runAt = new Date().toISOString()

  /** @type {Record<string, CategoryScores[]>} */
  const perThemeRuns = {}

  for (const theme of THEMES) {
    perThemeRuns[theme] = []
    for (let i = 1; i <= RUNS; i++) {
      process.stderr.write(`[lighthouse:audit] ${theme} run ${i}/${RUNS} → ${targetUrl}\n`)
      try {
        const { scores, lhr } = await runOnce(targetUrl, theme)
        perThemeRuns[theme].push(scores)
        const reportPath = path.join(REPORTS_DIR, `${theme}-run${i}.json`)
        await writeFile(reportPath, JSON.stringify(lhr, null, 2), 'utf8')
        process.stderr.write(
          `[lighthouse:audit]   scores: P=${scores.performance} ` +
            `A=${scores.accessibility} ` +
            `BP=${scores['best-practices']} ` +
            `SEO=${scores.seo}\n`,
        )
      } catch (err) {
        process.stderr.write(
          `[lighthouse:audit]   run failed: ${err instanceof Error ? err.message : String(err)}\n`,
        )
        // Continue with the remaining runs — median is best-effort.
      }
    }
  }

  const summaryLines = [
    '# PR #13 — Lighthouse audit summary (plan D6 manual artifact)',
    '',
    `- Target: \`${targetUrl}\` (preview build per D6 lock)`,
    `- Runs per theme: ${RUNS}`,
    `- Captured at: ${runAt}`,
    `- Node: ${process.version}`,
    `- Harness: \`apps/frontend/lighthouse/run-audit.mjs\``,
    '',
    '**Not a CI gate.** Plan D6 locks Lighthouse as a manual PR acceptance',
    'artifact. Targets are Performance / Accessibility / Best Practices / SEO',
    'all ≥ 90 on the median of a 3-run window. Reviewer reads this summary and',
    'attaches it (plus the JSON reports) to the PR body.',
    '',
    '## Median scores',
    '',
  ]

  for (const theme of THEMES) {
    const runs = perThemeRuns[theme] ?? []
    summaryLines.push(markdownRowsForTheme(theme, runs))
    summaryLines.push('')
  }

  summaryLines.push('## Reproduction', '')
  summaryLines.push('```bash')
  summaryLines.push('# 1) Build + preview (separate terminal, keep running)')
  summaryLines.push('pnpm --filter @dprk-cti/frontend run build')
  summaryLines.push('pnpm --filter @dprk-cti/frontend run preview')
  summaryLines.push('')
  summaryLines.push('# 2) BE on :8000 + seeded session cookie for /dashboard')
  summaryLines.push('#    (see apps/frontend/lighthouse/README.md)')
  summaryLines.push('')
  summaryLines.push('# 3) Audit')
  summaryLines.push('pnpm --filter @dprk-cti/frontend run lighthouse:audit')
  summaryLines.push('```')

  const summaryPath = path.join(REPORTS_DIR, 'SUMMARY.md')
  await writeFile(summaryPath, summaryLines.join('\n') + '\n', 'utf8')
  process.stderr.write(`[lighthouse:audit] wrote ${summaryPath}\n`)

  // Always exit 0 — see D6 lock. Reviewer decides acceptance.
  process.exit(0)
}

main().catch((err) => {
  process.stderr.write(
    `[lighthouse:audit] fatal: ${err instanceof Error ? err.stack ?? err.message : String(err)}\n`,
  )
  // Even on fatal, exit 0 so a harness bug never breaks a local
  // dev loop. Script logs stderr for diagnosis.
  process.exit(0)
})
