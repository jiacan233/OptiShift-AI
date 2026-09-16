/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#10243E',
        canvas: '#F3F7F8',
        teal: {
          50: '#EBFAF6',
          100: '#D5F4EB',
          500: '#1A9A80',
          600: '#0F806B',
          700: '#0B6657',
        },
      },
      boxShadow: {
        panel: '0 10px 30px rgba(16, 36, 62, 0.07)',
        drawer: '-12px 0 40px rgba(16, 36, 62, 0.16)',
      },
    },
  },
  plugins: [],
}
