# Acme dashboard (Vite + React + TypeScript + Tailwind)

This package is the componentized dashboard source. The demo ships a zero-dependency static dashboard at
`interface/static/dashboard/index.html` so `docker compose` works without Node.js.

When Node.js and npm are available:

```bash
cd interface/frontend
npm ci
npm run build
```

The build emits files under `interface/frontend/dist/`. To replace the default static dashboard, copy `dist/*` into
`interface/static/dashboard/` (after backing up the existing `index.html` if you still need the CDN version).
