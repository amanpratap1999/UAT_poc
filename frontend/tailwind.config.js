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
const config = {
    darkMode: "class",
    content: ["./index.html", "./src/**/*.{ts,tsx,js,jsx}"],
    theme: {
        // Override ALL Tailwind defaults with our design tokens
        colors: {
            transparent: "transparent",
            current: "currentColor",
            // ── Semantic tokens (CSS-var backed — flip in .theme-dark) ──────────
            canvas: "rgb(var(--canvas) / <alpha-value>)",
            card: "rgb(var(--card) / <alpha-value>)",
            line: "rgb(var(--line) / <alpha-value>)",
            "line-strong": "rgb(var(--line-strong) / <alpha-value>)",
            ink: "rgb(var(--ink) / <alpha-value>)",
            body: "rgb(var(--body) / <alpha-value>)",
            muted: "rgb(var(--muted) / <alpha-value>)",
            faint: "rgb(var(--faint) / <alpha-value>)",
            accent: "rgb(var(--accent) / <alpha-value>)",
            "accent-soft": "rgb(var(--accent-soft) / <alpha-value>)",
            "btn-primary": "rgb(var(--btn-primary) / <alpha-value>)",
            "btn-primary-hover": "rgb(var(--btn-primary-hover) / <alpha-value>)",
            "btn-primary-fg": "rgb(var(--btn-primary-fg) / <alpha-value>)",
            // ── Run status (semantic, flips) ────────────────────────────────────
            "status-queued": "rgb(var(--status-queued) / <alpha-value>)",
            "status-running": "rgb(var(--status-running) / <alpha-value>)",
            "status-completed": "rgb(var(--status-completed) / <alpha-value>)",
            "status-failed": "rgb(var(--status-failed) / <alpha-value>)",
            "status-blocked": "rgb(var(--status-blocked) / <alpha-value>)",
            "status-cancelled": "rgb(var(--status-cancelled) / <alpha-value>)",
            // ── Classification colours (semantic, flips; never signal-teal) ─────
            "class-business-rule": "rgb(var(--class-business-rule) / <alpha-value>)",
            "class-app-bug": "rgb(var(--class-app-bug) / <alpha-value>)",
            "class-config-diff": "rgb(var(--class-config-diff) / <alpha-value>)",
            "class-expected-custom": "rgb(var(--class-expected-custom) / <alpha-value>)",
            "class-agent-issue": "rgb(var(--class-agent-issue) / <alpha-value>)",
            "class-unknown": "rgb(var(--class-unknown) / <alpha-value>)",
            // ── Legacy dark palette (permanent dark chrome / theater) ──────────
            "graphite-950": "#14161A",
            "graphite-900": "#171A20",
            "graphite-800": "#1C1F26",
            "graphite-700": "#232833",
            "graphite-600": "#2C313C",
            "ink-100": "#E8E6E1",
            "ink-200": "#CFCCC6",
            "ink-300": "#B9B5AF",
            "ink-400": "#9B9690",
            "ink-600": "#5A5750",
            // Perception / live-state accent — RESERVED (Invariant 1)
            "signal-teal": "#4DD8C4",
            // Amber family (dark-theater warnings)
            "amber-300": "#F2C179",
            "amber-400": "#EDB25A",
            "amber-500": "#E8A33D",
            // Red family (dark-theater failures)
            "red-400": "#E08585",
            "red-500": "#C47070",
            "red-900": "#2E1A1E",
            "red-950": "#241418",
            // Utility
            white: "#FFFFFF",
            black: "#000000",
        },
        fontFamily: {
            display: ['"General Sans"', '"Neue Montreal"', '"Inter"', "sans-serif"],
            body: ['"Inter"', '"IBM Plex Sans"', "system-ui", "sans-serif"],
            mono: ['"IBM Plex Mono"', '"JetBrains Mono"', '"Fira Code"', "monospace"],
        },
        fontSize: {
            "2xs": ["0.625rem", { lineHeight: "1rem" }],
            "3xs": ["0.5625rem", { lineHeight: "0.75rem" }],
            xs: ["0.75rem", { lineHeight: "1rem" }],
            sm: ["0.875rem", { lineHeight: "1.25rem" }],
            base: ["1rem", { lineHeight: "1.5rem" }],
            lg: ["1.125rem", { lineHeight: "1.75rem" }],
            xl: ["1.25rem", { lineHeight: "1.75rem" }],
            "2xl": ["1.5rem", { lineHeight: "2rem" }],
            "3xl": ["1.875rem", { lineHeight: "2.25rem" }],
            "4xl": ["2.25rem", { lineHeight: "2.5rem" }],
        },
        spacing: {
            px: "1px",
            "0": "0",
            "0.5": "0.125rem",
            "1": "0.25rem",
            "1.5": "0.375rem",
            "2": "0.5rem",
            "2.5": "0.625rem",
            "3": "0.75rem",
            "3.5": "0.875rem",
            "4": "1rem",
            "5": "1.25rem",
            "6": "1.5rem",
            "7": "1.75rem",
            "8": "2rem",
            "9": "2.25rem",
            "10": "2.5rem",
            "11": "2.75rem",
            "12": "3rem",
            "14": "3.5rem",
            "16": "4rem",
            "20": "5rem",
            "24": "6rem",
            "28": "7rem",
            "32": "8rem",
            "36": "9rem",
            "40": "10rem",
            "44": "11rem",
            "48": "12rem",
            "52": "13rem",
            "56": "14rem",
            "60": "15rem",
            "64": "16rem",
            "72": "18rem",
            "80": "20rem",
            "96": "24rem",
        },
        extend: {
            borderRadius: {
                sm: "0.25rem",
                DEFAULT: "0.375rem",
                md: "0.5rem",
                lg: "0.75rem",
                xl: "1rem",
                "2xl": "1.25rem",
                full: "9999px",
            },
            boxShadow: {
                // Light-workspace elevation — blue-tinted, Stripe-style
                card: "0 1px 2px rgba(16, 24, 40, 0.05), 0 1px 3px rgba(16, 24, 40, 0.06)",
                raise: "0 2px 4px -2px rgba(16, 24, 40, 0.06), 0 4px 12px -2px rgba(16, 24, 40, 0.08)",
                float: "0 12px 32px -8px rgba(16, 24, 40, 0.18), 0 4px 12px -4px rgba(16, 24, 40, 0.10)",
                // Dark-theater elevation
                theater: "0 8px 32px rgba(0, 0, 0, 0.5)",
                glow: "0 0 24px rgba(77, 216, 196, 0.25)",
            },
            ringColor: {
                DEFAULT: "#4DD8C4",
            },
            keyframes: {
                "reticle-pulse": {
                    "0%, 100%": { opacity: "1", transform: "scale(1)" },
                    "50%": { opacity: "0.4", transform: "scale(1.08)" },
                },
                "fade-in": {
                    "0%": { opacity: "0", transform: "translateY(4px)" },
                    "100%": { opacity: "1", transform: "translateY(0)" },
                },
                "slide-in-left": {
                    "0%": { opacity: "0", transform: "translateX(-8px)" },
                    "100%": { opacity: "1", transform: "translateX(0)" },
                },
            },
            animation: {
                "reticle-pulse": "reticle-pulse 1.2s ease-in-out infinite",
                "fade-in": "fade-in 0.15s ease-out",
                "slide-in-left": "slide-in-left 0.15s ease-out",
            },
        },
    },
    plugins: [],
};
export default config;
