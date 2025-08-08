# PingPong College Study Dashboard - UI

This is the UI for the PingPong College Study dashboard.

## Overview

- Built with `SvelteKit` (Svelte 5) and `TypeScript`
- `pnpm` for package management
- Deployed as a static site via `@sveltejs/adapter-static`, served by Nginx (see `web/Dockerfile`)
- `Tailwind CSS v4` via `@tailwindcss/vite`
- Uses `bits-ui`, `lucide` icons, `tailwind-variants`, and custom components

## Development

### Pre-reqs

- Use Node `v22.18.0` (other versions may work, but not guaranteed)
- Use [`pnpm`](https://pnpm.io/) for package management
- Run the PingPong API, DB, and related services. The easiest way is via Docker using the repo script: `./start-dev-docker.sh` (from the repo root)

### Running the live-reload dev server

Install dependencies:

```
pnpm install
```

Run the dev server:

```
pnpm dev
```

The Study Dashboard will be available at `http://localhost:5173` (Vite will pick a different port if 5173 is in use).

### Code quality

- `pnpm check` — Runs `svelte-check` with the local `tsconfig.json`
- `pnpm lint` — Runs `prettier --check` and `eslint`
- `pnpm format` — Formats the codebase with Prettier

## Deployment

This app builds to a static site via `adapter-static`.

- Build locally with:

```
pnpm build
```

- In containerized environments, the multi-stage `web/Dockerfile` builds both the main PingPong site and the Study Dashboard, and serves them via Nginx. The Study site output is copied to `/usr/share/nginx/html/study`.
- Nginx configuration is templated via `web/default.conf.template`. Runtime `ARG`/`ENV` values are typically set/overridden by `docker-compose` per environment.

If the API runs on a non-default host/port, update the `/api` proxy target in `vite.config.ts` for local development.
