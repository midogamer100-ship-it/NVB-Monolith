/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: {
          50: "#eef3fb",
          100: "#d6e1f3",
          200: "#adc3e7",
          300: "#7c9fd6",
          400: "#4d77bf",
          500: "#2f5aa3",
          600: "#234684",
          700: "#1c386a",
          800: "#162c54",
          900: "#0f1f3d",
          950: "#0a1529",
        },
      },
      fontFamily: {
        sans: ["Inter", "Segoe UI", "system-ui", "-apple-system", "Roboto", "Helvetica Neue", "Arial", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(15,31,61,0.06), 0 1px 3px rgba(15,31,61,0.08)",
      },
    },
  },
  plugins: [],
};
