/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['selector', '[data-theme=\'dark\']'],
  theme: {
    extend: {
      colors: {
        bg: 'var(--bg)',
        card: 'var(--card)',
        signal: 'var(--signal)',
        ice: 'var(--ice)',
        danger: 'var(--danger)',
        warn: 'var(--warn)',
        t1: 'var(--text)',
        t2: 'var(--text-2)',
        t3: 'var(--text-3)',
      },
      fontFamily: {
        sans: ['Geist Sans', 'PingFang SC', 'Microsoft YaHei', 'system-ui', 'sans-serif'],
        mono: ['Geist Mono', 'SF Mono', 'Consolas', 'monospace'],
      },
      borderRadius: { ctrl: '8px', card: '16px', float: '22px' },
    },
  },
  plugins: [],
}
