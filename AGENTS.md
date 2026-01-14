# AGENTS.md

This file guides automated agents and contributors working in this repository. It mirrors CLAUDE.md and reflects current codebase practices.

## Project Overview

PingPong is an educational AI assistant platform with:
- Backend: FastAPI (Python 3.11+), async SQLAlchemy, Pydantic v2
- Frontend: SvelteKit with TypeScript
  - `web/pingpong` (Svelte 4, Tailwind v3, Flowbite-Svelte)
  - `web/study` (Svelte 5, Tailwind v4, bits-ui)
- Authorization: OpenFGA
- Authentication: JWT (magic links, SAML/SSO)
- LMS: Canvas LTI 1.3
- DB: Postgres (prod) or SQLite (dev/tests)

## Repo Layout

- `pingpong/` FastAPI app, models, schemas, authz, integrations
- `alembic/` database migrations
- `web/pingpong/` main SvelteKit UI (Svelte 4)
- `web/study/` study dashboard UI (Svelte 5)
- `scripts/` one-off scripts and CLI helpers
- `config.toml`, `test_config.toml` configuration defaults/tests

## Common Development Commands

### Backend (repo root)

```bash
poetry install --with dev
CONFIG_PATH=config.local.toml poetry run fastapi dev pingpong --port 8000 --host 0.0.0.0 --reload
poetry run pytest
poetry run alembic revision --autogenerate -m "description of change"
poetry run python -m pingpong db migrate
```

### Frontend: main app (`web/pingpong`)

```bash
pnpm install
pnpm dev
pnpm check
pnpm lint
pnpm format
pnpm test
```

### Frontend: study dashboard (`web/study`)

```bash
pnpm install
pnpm dev
pnpm check
pnpm lint
pnpm format
```

### Docker

```bash
./start-dev-docker.sh
```

## Backend Architecture and Patterns

- Request middleware order: session parsing -> authz session -> DB session -> logging. Access `request.state.db`, `request.state.authz`, `request.state.session`.
- Authorization uses composable expressions in `pingpong/permission.py` (`Authz`, `LoggedIn`, `InstitutionAdmin`) and OpenFGA model in `pingpong/authz/authz.fga.json`.
- Database is async SQLAlchemy; use `config.db.driver.async_session()` or `@db_session_handler` for non-request tasks.
- Schemas live in `pingpong/schemas.py` (Pydantic v2). Return schemas directly from endpoints.
- Central config is `pingpong/config.py` via `BaseSettings` and TOML (`CONFIG_PATH=config.local.toml`).

## Frontend Architecture and Patterns

### `web/pingpong` (Svelte 4)

- API client lives in `web/pingpong/src/lib/api.ts`. Use `expandResponse`/`explodeResponse` helpers and streaming utilities in `src/lib/streams.ts`.
- State is managed with Svelte stores; conversation state uses `ThreadManager` in `src/lib/stores/thread.ts`.
- UI uses Tailwind and Flowbite-Svelte components, plus custom components in `src/lib/components`.

### `web/study` (Svelte 5)

- Svelte 5 runes and `.svelte.ts` modules appear throughout; follow those patterns.
- UI uses Tailwind v4, bits-ui, and components under `src/lib/components`/`src/lib/components/ui`.

## Code Style and Conventions

### Python
- Follow existing async-first patterns and type hints.
- Keep imports grouped: stdlib, third-party, local.
- Use logging via `logging.getLogger(__name__)` and raise `HTTPException` for HTTP errors.
- Prefer Pydantic models for request/response shapes instead of raw dicts.

### Svelte/TypeScript

`web/pingpong`:
- Prettier config uses 2 spaces, single quotes, no trailing commas, print width 100.
- ESLint with `@typescript-eslint` and `eslint-plugin-svelte`.

`web/study`:
- Prettier uses tabs, single quotes, no trailing commas, print width 100.
- ESLint flat config; keep formatting consistent with existing files.

## Adding New API Endpoints

1. Add route handlers in `pingpong/server.py` alongside related endpoints.
2. Add/extend Pydantic schemas in `pingpong/schemas.py`.
3. Apply permission expressions via `Depends(Authz(...))`.
4. Implement client call in `web/pingpong/src/lib/api.ts` (and update study client if needed).
5. Add tests under `pingpong/test_*.py` using fixtures in `conftest.py` and helpers in `pingpong/testutil.py`.

## Database Migrations

1. Update models in `pingpong/models.py`.
2. Generate migration: `poetry run alembic revision --autogenerate -m "description"`.
3. Review migration in `alembic/versions/`.
4. Apply: `poetry run python -m pingpong db migrate`.

## Development Notes

- Tests load `test_config.toml` automatically (`conftest.py` sets `CONFIG_PATH`).
- Dev email uses the mock sender; check API console output for magic links.
- LTI flows use `sessionStorage` for iframe-safe session tokens in the main UI.

# MCP Server Documentation

This project uses multiple MCP servers to provide comprehensive documentation access.

## Available MCP Servers

### Svelte MCP Server

You have access to comprehensive Svelte 5 and SvelteKit documentation. Here's how to use the available tools effectively:

#### Available Tools:

**1. list-sections**
- Use this FIRST to discover all available documentation sections
- Returns a structured list with titles, use_cases, and paths
- When asked about Svelte or SvelteKit topics, ALWAYS use this tool at the start to find relevant sections

**2. get-documentation**
- Retrieves full documentation content for specific sections
- Accepts single or multiple sections
- After calling list-sections, you MUST analyze the returned documentation (especially the use_cases field) and then fetch ALL relevant sections for the user's task

**3. svelte-autofixer**
- Analyzes Svelte code and returns issues and suggestions
- You MUST use this tool whenever writing Svelte code before sending it to the user
- Keep calling it until no issues or suggestions are returned

**4. playground-link**
- Generates a Svelte Playground link with the provided code
- After completing the code, ask the user if they want a playground link
- NEVER call this if code was written to files in their project

### Flowbite-Svelte MCP Server

You have access to comprehensive Flowbite-Svelte component documentation. Here's how to use the available tools effectively:

#### Available Tools:

**1. findComponent**
- Use this FIRST to discover components by name or category
- Returns component information including the documentation path
- When asked about Flowbite-Svelte components, ALWAYS use this tool to locate the correct component before fetching documentation
- Example queries: 'Button', 'CardPlaceholder', 'form checkbox'

**2. getComponentList**
- Lists all available Flowbite-Svelte components with their categories
- Use this to discover what components are available or to help users explore component options

**3. getComponentDoc**
- Retrieves full documentation content for a specific component
- Accepts the component path found using findComponent
- After calling findComponent, use this tool to fetch complete documentation including usage examples, props, and best practices

**4. searchDocs**
- Performs full-text search across all Flowbite-Svelte documentation
- Use this when you need to find specific information that might span multiple components or when the user asks about features or patterns

## Workflow Guidelines

### When building Svelte components with Flowbite-Svelte:

1. **Start with Svelte documentation**: Use `list-sections` to understand which Svelte concepts are needed
2. **Fetch relevant Svelte docs**: Use `get-documentation` to get all necessary Svelte sections
3. **Find Flowbite-Svelte components**: Use `findComponent` to locate the UI components needed
4. **Get component details**: Use `getComponentDoc` to fetch usage examples and props
5. **Write the code**: Combine Svelte patterns with Flowbite-Svelte components
6. **Validate the code**: Use `svelte-autofixer` to check for issues
7. **Offer playground**: Ask if the user wants a playground link (only if not writing to files)

### Best Practices:

- Always prioritize Svelte 5 runes and modern patterns
- Use Flowbite-Svelte components for consistent UI design
- Validate all code with svelte-autofixer before delivering
- Keep documentation lookups efficient by fetching multiple sections at once
