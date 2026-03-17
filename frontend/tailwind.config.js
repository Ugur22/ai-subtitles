import typography from '@tailwindcss/typography';

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      maxWidth: {
        '8xl': '1440px',
      },
      colors: {
        primary: {
          50: '#f5f3ff',
          100: '#ede9fe',
          200: '#ddd6fe',
          300: '#c4b5fd',
          400: '#a78bfa',
          500: '#8b5cf6',
          600: '#7c3aed',
          700: '#6d28d9',
          800: '#5b21b6',
          900: '#4c1d95',
        },
      },
      typography: {
        DEFAULT: {
          css: {
            color: '#1f2937',
            '--tw-prose-headings': '#111827',
            a: {
              color: '#6d28d9',
              '&:hover': {
                color: '#5b21b6',
              },
            },
            h2: {
              fontSize: '1rem',
              fontWeight: '700',
              marginTop: '1.25em',
              marginBottom: '0.5em',
              paddingBottom: '0.375em',
              borderBottom: '1px solid #e5e7eb',
            },
            h3: {
              fontSize: '0.875rem',
              fontWeight: '600',
              marginTop: '1em',
              marginBottom: '0.375em',
            },
            p: {
              marginTop: '0.5em',
              marginBottom: '0.5em',
            },
            ul: {
              marginTop: '0.375em',
              marginBottom: '0.375em',
            },
            ol: {
              marginTop: '0.375em',
              marginBottom: '0.375em',
            },
            li: {
              marginTop: '0.125em',
              marginBottom: '0.125em',
            },
            blockquote: {
              fontStyle: 'normal',
              borderLeftColor: '#818cf8',
              backgroundColor: '#eef2ff',
              borderRadius: '0 0.375rem 0.375rem 0',
              padding: '0.5em 1em',
              marginTop: '0.75em',
              marginBottom: '0.75em',
            },
            'blockquote p:first-of-type::before': {
              content: 'none',
            },
            'blockquote p:last-of-type::after': {
              content: 'none',
            },
          },
        },
      },
      animation: {
        'fade-in': 'fadeIn 0.3s ease-in-out',
        'slide-in': 'slideIn 0.3s ease-in-out',
        'progress-indeterminate': 'progressIndeterminate 1.5s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideIn: {
          '0%': { transform: 'translateY(10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        progressIndeterminate: {
          '0%': { transform: 'translateX(-100%)' },
          '50%': { transform: 'translateX(150%)' },
          '100%': { transform: 'translateX(-100%)' },
        },
      },
      boxShadow: {
        'glow': '0 0 30px rgba(99, 102, 241, 0.2)',
      },
    },
  },
  plugins: [typography],
} 