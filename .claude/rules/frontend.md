---
paths:
  - "frontend/src/**/*.ts"
  - "frontend/src/**/*.tsx"
  - "frontend/src/**/*.css"
---

# Frontend rules

## Stack
React 19, Vite 6, TypeScript 5.7, Tailwind 3, TanStack Query 5, axios, react-router 7, ESLint 9, Vitest 3.

## Layout (`frontend/src`)
- `components/features/<domain>/` holds feature UI (chat, transcription, speakers, jobs, search, summary, chapters, face-tagging); shared pieces are in `components/{common,layout,pages}`, and auth, admin and settings have their own folders.
- `hooks/use*.ts(x)` hold data and behavior; `services/api.ts` and `services/auth.ts` make the backend calls; `contexts/`, `types/`, `utils/` and `lib/` hold the rest. Query keys live in `lib/queryKeys.ts`.
- `services/api.ts`, `config.ts` and `App.tsx` are core modules: touching them makes the change Review tier.

## Rules
- Base URLs: `config.ts` exports `API_BASE_URL` and `getApiUrl`; use them and never hardcode a base URL.
- Server data goes through React Query.
- Never poll fast or forever. `/api/*` is proxied through Netlify to Cloud Run, so a tight polling loop drives backend cost; poll only while work is active, back off, and stop on completion and on error. The `polling` ratchet (`tools/ratchets/rules/`) enforces this.
- Keep types strict: no `any` to get past `tsc`. Shared job types are in `types/job.ts`.
- Match the neighbouring component before inventing a pattern, and style with Tailwind utility classes.
- Lint, TypeScript, Vite and Vitest configs and `package.json` are guard paths.

## Verification
- Vitest runs `*.test.ts` files next to the code they test (see `components/features/chat/*.test.ts`); there are no DOM or component tests yet. Put logic you change in a plain function or hook module and test it there.
- `make check` runs ESLint, `tsc` and Vitest. Say plainly when a visual change was not viewed in a browser.
