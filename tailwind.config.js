/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: { extend: { colors: { ink: '#172538', muted: '#677487', line: '#e7ebf0', paper: '#f7f8fa', brand: '#315bd6', teal: '#18816f' }, boxShadow: { card: '0 8px 28px rgba(24,42,72,.045)' } } },
  plugins: [],
}
