PingPong - UI
===

This is the UI for the PingPong app.


## Overview

 * Built with `SvelteKit` / `TypeScript`
 * `pnpm` for package management
 * Deployed with `node-adapter` in production -- containerized NodeJS server for pre-rendering & handling certain form submissions to pass along to the Python API.
 * Uses `Tailwind` with PostCSS
 * Uses `Flowbite-Svelte` for UI components, along with some custom-built components where the Flowbite components fall short (such as the FileUploader)

## Development

### Installation

 - Use Node `v21.1.0` (other versions probably work, but no guarantees)
 - Use [`pnpm`](https://pnpm.io/) for package management. (It's a lot faster than `npm` and `yarnpkg`.)

Install dependencies (including dev):
```
pnpm install
```

### Dev server

The dev server with live reload can be started on port 5173 with:

```
pnpm dev
```

**You need to run the Python API as well. See the other READMEs for more information!**

We use `vite` to build our code. See `vite.config.ts` (and affiliated config files) for more information.

### Code quality

The following static checks are performed when you create a pull request:

 - `vite check` - Runs TypeScript type-checking
 - `vite lint` -  Runs `eslint` and `prettier` formatting checks (hint: use `vite format` to automatically fix many issues!)
 - `vite test` - Runs unit tests through `vitest`

### Env

There is a `.env` checked into the repo with good defaults for development.

You can use an untracked version to configure your own if needed:

 - `API_PROTO` - The protocol (scheme) for the Python API (`http` in dev)
 - `API_HOST` - The host & port of the Python API (`localhost:8000` in dev)
 - `HOST` - Host to bind the node server to (default is `0.0.0.0`, but this does NOT apply to the dev server! Only when running with the `node-adapter`!)
 - `PORT` - Port to bind the node server to (default is `3000`, buthis does NOT apply to the dev server! Only when running with the `node-adapter`!)
 - `NODE_ENV` - Enables additional debugging when set to `development` vs `production`
 - `VITE_SENTRY_DSN` - For error reporting -- can leave empty in dev

## Deployment

The frontend is deployed using the `node-adapter` in a Docker container.

See the `Dockerfile` for more information.
(Note that the `ARG`s in the container are generally overridden by the `docker-compose` config for the given environment!)
