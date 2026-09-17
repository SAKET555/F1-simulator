/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        f1red: "#e10600",
        pitwall: "#0f1117",
        panel: "#1a1d27",
        border: "#2a2d3a",
      },
    },
  },
  plugins: [],
};
