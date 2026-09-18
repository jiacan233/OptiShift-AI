/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#10243E',
        canvas: '#F4F7FC',
        teal: {
          50: '#EFF6FF',
          100: '#DBEAFE',
          500: '#3B82F6',
          600: '#2563EB',
          700: '#1D4ED8',
        },
      },
      boxShadow: {
        'xs': '0 1px 3px rgba(15,23,42,.04)',
        panel: '0 10px 30px rgba(16, 36, 62, 0.07)',
        drawer: '-12px 0 40px rgba(16, 36, 62, 0.16)',
      },
    },
  },
  plugins: [],
}
