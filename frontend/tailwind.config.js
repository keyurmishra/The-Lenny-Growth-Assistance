/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Claude-inspired palette — warm neutrals with terracotta accent
        claude: {
          orange: '#d97706',
          'orange-light': '#fef3c7',
          'orange-dim': '#92400e',
        },
        // Warm surface colors (Claude's signature off-white / cream)
        surface: {
          primary: '#fafaf8',    // Main bg — warm off-white
          secondary: '#f4f4ef',  // Slightly darker warm cream
          tertiary: '#eeede8',   // Hover / active states
          chat: '#ffffff',       // Pure white for chat area
          input: '#ffffff',
        },
        // Sidebar colors — slightly darker warm gray
        sidebar: {
          bg: '#f0efeb',
          hover: '#e8e7e1',
          active: '#e2e1da',
          border: '#d8d7d0',
        },
        // Ink / text
        ink: {
          primary: '#1a1916',    // Almost black, warm-tinted
          secondary: '#44433e',  // Medium warm gray
          tertiary: '#8a8880',   // Light warm gray
          muted: '#b5b3ae',      // Very light
        },
        // Accent — Claude's warm orange/terracotta
        accent: {
          50:  '#fef9f0',
          100: '#fef3c7',
          200: '#fde68a',
          300: '#fbbf24',
          400: '#f59e0b',
          500: '#d97706',
          600: '#b45309',
          700: '#92400e',
        },
        // Separator / border
        border: {
          light: '#e8e7e1',
          medium: '#d4d3cc',
        },
      },
      fontFamily: {
        sans: ['Söhne', 'Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      animation: {
        'fade-in': 'fadeIn 0.2s ease-out',
        'slide-in': 'slideIn 0.2s ease-out',
        'pulse-dot': 'pulseDot 1.4s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0', transform: 'translateY(4px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        slideIn: {
          '0%': { opacity: '0', transform: 'translateX(-8px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        pulseDot: {
          '0%, 80%, 100%': { opacity: '0.25', transform: 'scale(0.8)' },
          '40%': { opacity: '1', transform: 'scale(1)' },
        },
      },
      maxWidth: {
        'chat': '46rem',
      },
    },
  },
  plugins: [],
}
