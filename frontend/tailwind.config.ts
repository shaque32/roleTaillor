import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // ink.faint darkened from #94a3b8 (2.6:1, fails AA) to #5b6779 (5.6:1 on white)
        ink: { DEFAULT: "#0f172a", muted: "#475569", faint: "#5b6779" },
        brand: {
          50: "#eef4ff",
          100: "#dbe6fe",
          200: "#bfd0fd",
          300: "#93adf8",
          400: "#5f84ea",
          500: "#3b63d9",
          600: "#2f50b8",
          700: "#263f91",
          800: "#1e3272",
        },
        surface: { DEFAULT: "#ffffff", page: "#f6f7fb", sunken: "#f1f4f9" },
        line: { DEFAULT: "#e5e9f0", field: "#8590a2" }, // field = 3.2:1 on white (WCAG 1.4.11)
      },
      fontFamily: { sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"] },
      // Global softening. Files we may not edit (ResumeUpload, BillingCard) pick this up for free.
      borderRadius: { md: "0.625rem", lg: "0.875rem", xl: "1.125rem", "2xl": "1.5rem" },
      boxShadow: {
        card: "0 1px 2px rgb(15 23 42 / 0.04), 0 4px 16px -4px rgb(15 23 42 / 0.08)",
        pop: "0 2px 6px rgb(15 23 42 / 0.06), 0 12px 32px -8px rgb(15 23 42 / 0.18)",
      },
      keyframes: {
        aurora: { from: { backgroundPosition: "50% 50%, 50% 50%" }, to: { backgroundPosition: "350% 50%, 350% 50%" } },
        shine: { "0%": { backgroundPosition: "100% 0" }, "100%": { backgroundPosition: "-100% 0" } },
        "pop-in": { from: { opacity: "0", transform: "translateY(4px) scale(0.98)" }, to: { opacity: "1", transform: "none" } },
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        shimmer: { from: { backgroundPosition: "200% 0" }, to: { backgroundPosition: "-200% 0" } },
      },
      animation: {
        aurora: "aurora 60s linear infinite",
        shine: "shine 3s linear infinite",
        "pop-in": "pop-in 140ms ease-out", // no fill-mode: must not leave a transform behind
        "fade-in": "fade-in 200ms ease-out",
        shimmer: "shimmer 1.6s linear infinite",
      },
    },
  },
  plugins: [],
};
export default config;
