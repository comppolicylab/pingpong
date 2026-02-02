# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

PingPong is an educational AI assistant platform built with:
- **Backend**: FastAPI (Python 3.11+) with SQLAlchemy (async)
- **Frontend**: SvelteKit with TypeScript
- **Authorization**: OpenFGA (fine-grained authorization)
- **Authentication**: JWT-based (magic links, SAML/SSO)
- **LMS Integration**: Canvas LTI 1.3
- **Database**: PostgreSQL (production) or SQLite (development/tests)

## Common Development Commands

### Backend (Python API)

```bash
# Install dependencies
poetry install --with dev

# Run development server with auto-reload
CONFIG_PATH=config.local.toml poetry run fastapi dev pingpong --port 8000 --host 0.0.0.0 --reload

# Alternative: run with uvicorn directly
poetry run uvicorn pingpong:server --port 8000 --workers 1 --reload

# Run tests
poetry run pytest

# Run specific test file
poetry run pytest path/to/test_file.py

# Run specific test
poetry run pytest path/to/test_file.py::test_function_name

# Database migrations - create new migration
poetry run alembic revision --autogenerate -m "description of change"

# Database migrations - apply migrations
poetry run python -m pingpong db migrate
```

### Frontend (SvelteKit)

```bash
# Change to frontend directory
cd web/pingpong

# Install dependencies
pnpm install

# Run development server (with live reload)
pnpm dev

# Type checking
pnpm check

# Linting and formatting check
pnpm lint

# Auto-fix formatting
pnpm format

# Run tests
pnpm test

# Build for production
pnpm build
```

### Docker Development

```bash
# Start all services (DB, OpenFGA, API) in Docker
./start-dev-docker.sh

# Note: You'll likely want to stop the pingpong-srv-1 container
# and run the Python API locally for faster development iteration
```

## High-Level Architecture

### Backend Architecture

**Request Flow:**
1. Request arrives at FastAPI app
2. Middleware stack processes in order:
   - `parse_session_token` - Parse JWT and populate user info
   - `begin_authz_session` - Create OpenFGA client connection
   - `begin_db_session` - Create async DB session with auto-commit
   - `log_request` - Log metrics and performance data
3. Route handler executes with access to `request.state.db`, `request.state.authz`, `request.state.session`
4. Middleware auto-commits DB transaction on success (status < 400) or rolls back on error

**Authorization System:**
- Two-layer auth: Authentication (JWT/SAML) + Fine-grained authorization (OpenFGA)
- Permission checks use composable expressions in `pingpong/permission.py`:
  - `Authz(relation, target)` - Direct OpenFGA check
  - `LoggedIn()` - User must be authenticated
  - `InstitutionAdmin()` - User must be admin of institution
  - Expressions support `|` (Or), `&` (And), `~` (Not) operations
  - Built-in per-request caching to avoid redundant checks
- OpenFGA client in `pingpong/authz/openfga.py` wraps SDK with async operations
- Authorization model defined in `pingpong/authz/authz.fga.json`

**Database Layer:**
- All operations are async using SQLAlchemy's async API
- Database abstraction via Glowplug library
- Access sessions via `config.db.driver.async_session()`
- Use `@db_session_handler` decorator for automatic session management with retry
- Models in `pingpong/models.py` inherit from `Base(AsyncAttrs, DeclarativeBase)`

**Key Model Relationships:**
```
User ─── UserClassRole ─── Class
User ─── ExternalLogin
Class ─── Thread ─── Message
Class ─── Assistant ─── Run
Assistant ─── VectorStore
Thread ─── Run ─── ToolCall
Institution ─── Class
Institution ─── User (admins)
```

**Configuration:**
- Single `config` object from `pingpong/config.py`
- Uses Pydantic `BaseSettings` with TOML file support
- Load custom config: `CONFIG_PATH=config.local.toml poetry run ...`
- Test config: `test_config.toml` (automatically loaded by pytest via `conftest.py`)

### Frontend Architecture

**Routing:**
- File-based routing in `web/pingpong/src/routes/`
- Key routes:
  - `/group/[classId]/` - Class view
  - `/group/[classId]/thread/[threadId]/` - Thread conversation
  - `/group/[classId]/assistant/[assistantId]/` - Assistant view
  - `/admin/` - Admin dashboard
  - `/lti/` - LTI integration flows

**API Client:**
- Centralized in `src/lib/api.ts` (3,700+ lines)
- All HTTP methods wrapped: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`
- Responses include `$status` field for consistent error handling
- Streaming support for real-time message/run updates
- Helper functions:
  - `expandResponse()` - returns `{ $status, error, data }`
  - `explodeResponse()` - throws error or returns data
  - `isErrorResponse()` - type guard for errors

**State Management:**
- Svelte stores for reactive state
- `ThreadManager` class manages conversation state:
  - Holds messages, run status, error state
  - Derived stores: `messages`, `loading`, `error`, `participants`
  - Operations: `postMessage()`, `fetchMore()`, `publish()`, `delete()`
  - Handles optimistic updates and rollback on errors

**Streaming Architecture:**
- Server-sent event streams for real-time responses
- Stream chunks: `MessageCreated`, `MessageDelta`, `ToolCallCreated`, `ToolCallDelta`, `Done`, `Error`
- Custom `TextLineStream` and `JSONStream` utilities in `src/lib/streams.ts`
- Optimistic UI updates while streaming

**Authentication:**
- Session tokens in cookies for standard auth
- `sessionStorage` for LTI iframe contexts (third-party cookie blocking)
- Anonymous access via share tokens (`X-Anonymous-Link-Share` header)
- Anonymous sessions via session tokens (`X-Anonymous-Thread-Session` header)

## Important Patterns

### Database Migrations

1. Make changes to SQLAlchemy models in `pingpong/models.py`
2. Generate migration: `poetry run alembic revision --autogenerate -m "description"`
3. Review generated migration file in `alembic/versions/`
4. Apply migration: `poetry run python -m pingpong db migrate`

### Testing

**Backend Tests:**
- Use pytest fixtures from `conftest.py`: `config`, `db`, `api`, `user`, `authz`, `now`
- Tests automatically use `test_config.toml` and SQLite in-memory database
- Mock OpenFGA server available via `authz` fixture
- Example:
```python
@pytest.mark.asyncio
async def api(api, valid_user_token):
    response = api.get("/api/v1/classes", headers={"Authorization": f"Bearer {valid_user_token}"})
    assert response.status_code == 200
```

**Frontend Tests:**
- Run with `pnpm test` in `web/pingpong/`
- Uses Vitest for unit testing

### Adding New API Endpoints

1. Add route handler to `pingpong/server.py` (grouped with related endpoints)
2. Add Pydantic schemas to `pingpong/schemas.py` for request/response models
3. Use permission expressions as dependencies: `Depends(Authz("viewer", "class:{class_id}"))`
4. Access DB via `request.state.db`, authz via `request.state.authz`
5. Return Pydantic models directly (FastAPI handles serialization)
6. Add corresponding client method to `web/pingpong/src/lib/api.ts`

### Working with OpenFGA

**Check permissions:**
```python
# In route handler
has_access = await request.state.authz.check("viewer", f"class:{class_id}", request.state.auth_user)
```

**Grant permissions:**
```python
await request.state.authz.write_safe(
    grants=[("viewer", f"class:{class_id}", f"user:{user_id}")],
    revokes=[]
)
```

**List accessible resources:**
```python
class_ids = await request.state.authz.list("viewer", "class", request.state.auth_user)
```

### Canvas LTI Integration

- LTI 1.3 registration endpoints in `/api/v1/lti/`
- Canvas OAuth2 flow: `/api/v1/auth/canvas`
- Canvas sync: syncs course rosters to `UserClassRole` entries
- Canvas connection stored per class in `Class.canvas_link`
- Session tokens passed via `lti_session` URL parameter to handle third-party cookie blocking

### File Uploads

**Backend:**
- Upload endpoint: `POST /api/v1/class/{class_id}/files`
- Files stored in S3 or local filesystem (configurable via `config.toml`)
- File records in `File` model with associations to classes/assistants

**Frontend:**
- Use `uploadFile()` from `api.ts` for XHR-based upload with progress tracking
- File picker in `ChatInput.svelte` component
- Attach files to messages via message attachments

### Streaming Messages

**Backend:**
- Stream chunks yielded as newline-delimited JSON
- Use `yield` in route handler to create streaming response
- Chunk types defined in `pingpong/schemas.py`

**Frontend:**
```typescript
const stream = await postMessage(threadId, content, attachments);
for await (const chunk of stream) {
  if (chunk.kind === 'message_delta') {
    // Update UI with new text
  } else if (chunk.kind === 'done') {
    // Stream complete
  }
}
```

## Project-Specific Notes

### Multi-Tenancy Model

The app uses a hierarchy: `Institution` → `Class` → `Assistant` / `Thread`
- Super users can create institutions
- Institution admins can create/manage classes within their institution
- Class instructors can create assistants and view all threads
- Students can only view their own threads

### API Key Management

- Classes can have their own OpenAI API keys (stored in `APIKey` model)
- Institutions can set default API keys for all classes
- Falls back to global API key in config if not set
- Supports both OpenAI and Azure OpenAI

### Anonymous Access

Two types of anonymous access:
1. **Share Links**: Public URLs to specific assistants/threads (via `X-Anonymous-Link-Share` header)
2. **Anonymous Sessions**: Temporary sessions for unauthenticated users (via `X-Anonymous-Thread-Session` header)

### Email in Development

The API uses a mock email sender in development that prints emails to the console.
Always check the API console output when expecting login emails.

### Voice Mode / Realtime API

- WebSocket endpoint: `WS /api/v1/class/{class_id}/threads/{thread_id}/realtime`
- Voice recordings stored in `VoiceModeRecording` model
- Transcription available via `GET /api/v1/thread/{thread_id}/recording/{recording_id}/transcript`
