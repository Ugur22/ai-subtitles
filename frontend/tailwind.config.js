import typography from '@tailwindcss/typography';

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
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
        base:        'var(--bg-base)',
        subtle:      'var(--bg-subtle)',
        surface:     'var(--bg-surface)',
        overlay:     'var(--bg-overlay)',
        accent:      'var(--accent)',
        'accent-dim':'var(--accent-dim)',
        'border-subtle':  'var(--border-subtle)',
        'border-default': 'var(--border-default)',
        'text-primary':   'var(--text-primary)',
        'text-secondary': 'var(--text-secondary)',
        'text-tertiary':  'var(--text-tertiary)',
        'c-success':  'var(--c-success)',
        'c-error':    'var(--c-error)',
      },
      typography: {
        DEFAULT: {
          css: {
            color: 'var(--text-primary)',
            '--tw-prose-headings': 'var(--text-primary)',
            '--tw-prose-body': 'var(--text-secondary)',
            '--tw-prose-bold': 'var(--text-primary)',
            '--tw-prose-links': 'var(--accent)',
            '--tw-prose-code': 'var(--text-primary)',
            '--tw-prose-hr': 'var(--border-subtle)',
            a: {
              color: 'var(--accent)',
              '&:hover': {
                color: 'var(--accent)',
                opacity: '0.8',
              },
            },
            h2: {
              fontSize: '1rem',
              fontWeight: '600',
              marginTop: '1.25em',
              marginBottom: '0.5em',
              paddingBottom: '0.375em',
              borderBottom: '1px solid var(--border-subtle)',
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
              borderLeftColor: 'var(--accent)',
              backgroundColor: 'var(--bg-surface)',
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
        'fade-in': 'fadeIn 0.2s ease-out',
        'slide-in': 'slideIn 0.25s cubic-bezier(0.16, 1, 0.3, 1)',
        'progress-indeterminate': 'progressIndeterminate 1.5s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: {
          '0%':   { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideIn: {
          '0%':   { transform: 'translateY(8px)', opacity: '0' },
          '100%': { transform: 'translateY(0)',   opacity: '1' },
        },
        progressIndeterminate: {
          '0%':   { transform: 'translateX(-100%)' },
          '50%':  { transform: 'translateX(150%)' },
          '100%': { transform: 'translateX(-100%)' },
        },
      },
    },
  },
  plugins: [typography],
}
