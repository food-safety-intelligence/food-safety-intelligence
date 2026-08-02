# Eatelligence web app

The Next.js front end of the Food Safety Intelligence project: map + search,
per-establishment risk detail, inspector worklist, methodology page, and the
embedded chat agent. Built as a static export (no API routes, no server at
runtime) and deployed to S3 + CloudFront by `.github/workflows/deploy-web.yml`
on merge to `main`.

The app reads only precomputed JSON from `public/data/` (Chicago at the root,
NYC under `nyc/`, LA under `la/`) — it never calls the model or a live API.
See the repo root `README.md` for the architecture and
`docs/interface_contracts.md` for the JSON schemas.

## Develop

Requires Node 20+. Works on a fresh clone with no AWS setup: `predev`
regenerates the search index and per-license detail bundles from the
committed JSON.

```bash
npm install
npm run dev      # http://localhost:3000
```

## Checks

```bash
npm run lint          # eslint
npx tsc --noEmit      # types
npm test              # vitest (pure-logic tests)
npm run build         # static export to out/
node e2e/smoke.mjs    # rendered-UI smoke over the built export
```

CI runs all of these; visible UI changes additionally need the screenshot
verification described in the repo `CLAUDE.md`.
