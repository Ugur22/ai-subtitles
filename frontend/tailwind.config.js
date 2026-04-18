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
            code: {
              color: 'var(--text-primary)',
              backgroundColor: 'var(--bg-subtle)',
              padding: '0.125em 0.375em',
              borderRadius: '0.25rem',
              fontSize: '0.875em',
              fontWeight: '500',
            },
            'code::before': { content: 'none' },
            'code::after': { content: 'none' },
            pre: {
              backgroundColor: 'var(--bg-base)',
              color: 'var(--text-primary)',
              border: '1px solid var(--border-subtle)',
              borderRadius: '0.5rem',
              padding: '0.875em 1em',
              marginTop: '0.75em',
              marginBottom: '0.75em',
              fontSize: '0.8125em',
              lineHeight: '1.6',
            },
            'pre code': {
              backgroundColor: 'transparent',
              padding: '0',
              border: 'none',
              fontWeight: '400',
            },
            table: {
              fontSize: '0.875em',
              borderCollapse: 'collapse',
            },
            thead: {
              borderBottom: '1px solid var(--border-default)',
            },
            'thead th': {
              color: 'var(--text-secondary)',
              fontWeight: '600',
              textTransform: 'uppercase',
              fontSize: '0.6875em',
              letterSpacing: '0.05em',
              padding: '0.5em 0.75em',
            },
            'tbody tr': {
              borderBottom: '1px solid var(--border-subtle)',
            },
            'tbody td': {
              padding: '0.5em 0.75em',
              color: 'var(--text-primary)',
            },
            hr: {
              borderColor: 'var(--border-subtle)',
              marginTop: '1.25em',
              marginBottom: '1.25em',
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
