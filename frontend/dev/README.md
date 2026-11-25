# Demo data and screenshots

Run the frontend against a fake backend and capture every screen (for before/after design comparisons).
Run each command from `frontend/`, in separate terminals.

```bash
# 1. Mock API on :8787 (fictional user "Jordan Lee"). Add MOCK_NEW_USER=1 for an account with no consent, resumes or workflows.
node dev/mock-api.mjs

# 2. Next.js dev server on :3000, pointed at the mock (env names from lib/server-config.ts)
API_BASE_URL=http://localhost:8787/v1 COOKIE_SECURE=false npm run dev

# 3. Screenshots: <outdir>/{desktop,mobile}-NN-name.png (1440x900 and 390x844, 2x)
node dev/screenshots.mjs <outdir>
```

`screenshots.mjs` needs Playwright resolvable from Node (`BASE_URL` overrides `http://localhost:3000`).
Mock state is in memory and resets when the mock restarts. Onboarding has no server-side "completed" flag: it is a
client-side flow reached after registering, so it is captured directly at `/onboarding`.
