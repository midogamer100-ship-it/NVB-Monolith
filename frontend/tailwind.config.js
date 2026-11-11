/** @type {import('tailwindcss').Config} */
// R&D bank on the Global Brands Group identity.
// The colour names "navy" and "teal" are kept so the page markup does not change:
//   navy = GBG ink and greys (headings, text, sidebar)
//   teal = GBG red (accents, primary buttons, focus rings)
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: {
          50: "#f3f2f2",
          100: "#e6e5e5",
          200: "#d1d2d3",
          300: "#bbbdbf",
          400: "#939597",
          500: "#7a7b7d",
          600: "#636466",
          700: "#4a4b4d",
          800: "#333234",
          900: "#201e1d",
          950: "#141312",
        },
        teal: {
          50: "#fdeced",
          100: "#fbd5d6",
          200: "#f7abae",
          300: "#f27c80",
          400: "#ef4a50",
          500: "#ed1c24",
          600: "#d4131a",
          700: "#c00000",
          800: "#9e0000",
          900: "#7a0000",
          950: "#4d0000",
        },
      },
      fontFamily: {
        sans: ["Inter Variable", "Inter", "Helvetica Neue", "Arial", "sans-serif"],
        display: ["Jost Variable", "Jost", "Century Gothic", "Futura", "sans-serif"],
      },
      borderRadius: {
        md: "2px",
        lg: "2px",
        xl: "4px",
        "2xl": "4px",
      },
      boxShadow: {
        card: "0 1px 2px rgba(32,30,29,0.06), 0 1px 3px rgba(32,30,29,0.08)",
      },
    },
  },
  plugins: [],
};
