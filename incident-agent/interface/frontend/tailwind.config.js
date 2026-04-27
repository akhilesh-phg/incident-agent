/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        acme: {
          navy: "#0b1426",
          slate: "#111c33",
          amber: "#f59e0b",
          mist: "#94a3b8",
        },
      },
    },
  },
  plugins: [],
};
