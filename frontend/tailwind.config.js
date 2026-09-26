/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        f1red: "#e10600",
        pitwall: "#0b0d13",
        panel: "#1a1d27",
        panel2: "#212536",
        border: "#2a2f40",
        ink: { 50: "#f4f5f8", 300: "#aab1c4", 500: "#727a90", 700: "#3a4054" },
      },
      fontFamily: {
        display: ['"Barlow Condensed"', "Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        card: "0 1px 0 rgba(255,255,255,.04) inset, 0 12px 28px -16px rgba(0,0,0,.75)",
        glow: "0 0 0 1px rgba(225,6,0,.35), 0 8px 30px -8px rgba(225,6,0,.35)",
      },
      keyframes: {
        fadeUp: { from: { opacity: 0, transform: "translateY(6px)" }, to: { opacity: 1, transform: "none" } },
        shimmer: { "100%": { transform: "translateX(100%)" } },
      },
      animation: { fadeUp: "fadeUp .35s ease both", shimmer: "shimmer 1.4s infinite" },
    },
  },
  plugins: [],
};
