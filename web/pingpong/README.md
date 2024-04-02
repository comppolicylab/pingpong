# PingPong - UI

This is the UI for the PingPong app.


## Overview

- Built with `SvelteKit` / `TypeScript`
- `pnpm` for package management
- Deployed with `node-adapter` in production -- containerized NodeJS server for pre-rendering & handling certain form submissions to pass along to the Python API.
- Uses `Tailwind` with PostCSS
- Uses `Flowbite-Svelte` for UI components, along with some custom-built components where the Flowbite components fall short (such as the FileUploader)

## Development


### Pre-reqs

- Use Node `v21.1.0` (other versions probably work, but no guarantees)
- Use [`pnpm`](https://pnpm.io/) for package management. (It's a lot faster than `npm` and `yarnpkg`.)
- Run the PingPong API, DB, and other services. The easiest way to do this is with Docker by running the `./start-dev-docker.sh` script.


### Running the live-reload FE dev server

This is how you run the FE dev server, which will reload as you make changes.

First install dependencies:

```
pnpm install
```

Then run the server with:

```
pnpm dev
```

PingPong will be available at `http://localhost:5173`.


### Code quality

The following static checks are performed when you create a pull request:

- `vite check` - Runs TypeScript type-checking
- `vite lint` - Runs `eslint` and `prettier` formatting checks (hint: use `vite format` to automatically fix many issues!)
- `vite test` - Runs unit tests through `vitest`


## Deployment

The frontend is deployed using the `node-adapter` in a Docker container.

See the `Dockerfile` for more information.
(Note that the `ARG`s in the container are generally overridden by the `docker-compose` config for the given environment!)
