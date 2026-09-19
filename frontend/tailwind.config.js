/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#10243E',
        canvas: '#F4F7FC',
        brand: {
          50: '#eff6ff',
          100: '#dbeafe',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
        },
        slate: {
          850: '#15202e',
        },
        teal: {
          50: '#EFF6FF',
          100: '#DBEAFE',
          500: '#3B82F6',
          600: '#2563EB',
          700: '#1D4ED8',
        },
      },
      borderRadius: {
        '2xl': '1rem',
        '3xl': '1.5rem',
        '4xl': '2rem',
      },
      boxShadow: {
        '2xs': '0 1px 2px 0 rgba(0, 0, 0, 0.03)',
        'xs': '0 1px 3px rgba(15,23,42,.04)',
        'inner-xs': 'inset 0 1px 2px 0 rgba(0, 0, 0, 0.04)',
        'soft': '0 10px 30px -4px rgba(0, 0, 0, 0.04)',
        'card': '0 4px 20px -2px rgba(0, 0, 0, 0.05)',
        'float': '0 20px 40px -10px rgba(0, 0, 0, 0.08)',
        panel: '0 10px 30px rgba(16, 36, 62, 0.07)',
        drawer: '-12px 0 40px rgba(16, 36, 62, 0.16)',
      },
    },
  },
  plugins: [],
}
