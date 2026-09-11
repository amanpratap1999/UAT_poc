import type { Config } from "tailwindcss";
/**
 * ─────────────────────────────────────────────────────────────────────────────
 * DESIGN SYSTEM — "Instrument Console" (light/dark mixed mode)
 *
 * Two contexts, one token set:
 *   • LIGHT WORKSPACE (default) — Dashboard, Runs, Findings, Knowledge, Settings.
 *     Warm paper canvas, white cards, hairline borders, deep-navy ink.
 *   • DARK CHROME/THEATER (.theme-dark) — Left rail, mobile nav, login brand
 *     panel, and the immersive Live Run view. Instrument-housing graphite.
 *
 * Semantic tokens are CSS-variable backed (flip under .theme-dark, see
 * src/styles/globals.css). The legacy graphite/ink names remain for components
 * that are permanently dark (theater chrome).
 *
 * Invariant: signal-teal (#4DD8C4) is reserved for perception / live state.
 * ─────────────────────────────────────────────────────────────────────────────
 */
declare const config: Config;
export default config;
