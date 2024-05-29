![PingPong](assets/owl@256px.png)

PingPong
===

A web app that helps students out with class assignments and logistics.


# Development

## Running locally

You need these things to use the app locally.
 - Postgres Database
 - OpenFGA Authz server
 - Python / Poetry to run the API
 - Pnpm to run the FrontEnd.
 - OpenAI API Key (for using the app)

The easiest way to run the DB and OpenFGA is through Docker.


### Quick setup

First, get access to the `config.dev.toml` file and put it in the root of your repo.

Assuming you have a Docker environment available,
the easiest way to start up development services is with the following script:

```
./start-dev-docker.sh
```

This will set up the DB (with all tables), OpenFGA, and the Python API in containers.

This does **not** build/start the Web UI; for that, see the [`web/pingpong/README.md`](web/pingpong/README.md).
You may also wish to stop the `pingpong-srv-1` container and replace it with an uncontainerized Python API for development (see below for instructions).


#### Running the Python API outside of Docker

The **Quick Setup** runs the Python API inside of Docker.
This makes development tedious if you need to make changes to the Python code.

To run the Python API outside of Docker,
first stop the `pingpong-srv-1` container in Docker (but keep the DB and authz containers running).

Next, create a file in the root of the repo named `config.local.toml`.
You can customize this file how you want, but the basic settings you need are:

```toml
log_level = "DEBUG"
public_url = "http://localhost:5173"
development = true

[db]
engine = "postgres"
host = "localhost"
user = "pingpong"
password = "pingpong"
database = "pingpong"

[auth]

[[auth.secret_keys]]
key = "not actually a secret!"

[authz]
type = "openfga"
scheme = "http"
host = "localhost"
store = "pingpong"
cfg = "./pingpong/authz/authz.fga.json"
key = "devkey"

[email]
type = "mock"
```

Then, run the following command to start the dev server:

```
CONFIG_PATH=config.local.toml poetry run uvicorn pingpong:server --port 8000 --host 0.0.0.0 --reload
```

This will start a `uvicorn` server that will automatically reload with code changes as you make them.


#### First time logging in

When you have everything running (including the UI; see [`web/pingpong/README.md`](web/pingpong/README.md)),
go to [http://localhost:5173](http://localhost:5173).
You should log in with a real email address you have access to.
In development, this user will be automatically promoted to a super user,
with full permissions to create new classes, etc.

You will receive a real email to that address with a link to log in to the dev server.
Click the link, you will be in!

#### Creating test users

You can use the `+` email trick to create test user accounts.

For example, if `joenudell@testdomain.com` is my real email address, I will use that as my super-user account.
Then, from the PingPong UI I can invite `joenudell+student1@testdomain.com` to be a student,
and `joenudell+teacher1@testdomain.com` to be an instructor in a class.

All of the login emails will be sent to `joenudell@testdomain.com`, so you can easily work with multiple users with different permissions.


## Adding new DB Migrations
If you need to modify the database, make your changes in the SQLAlchemy code, then run:

```
poetry run alembic revision --autogenerate -m "<description of change>"
```

Verify the migration is correct, check it into the repo, and apply it to the database by running:

```
poetry run python -m pingpong db migrate
```

## Authz

The OpenFGA authorization server has a [playground](http://localhost:3000/playground) that may be useful.


## Backend / API

We use `Python 3.11` and [`Poetry`](https://python-poetry.org/) for package management.

If you want to develop outside of a container using a live-reload server, do the following:

Run `poetry install --with dev` to install dependencies.

The following command runs the API in development mode:
```
poetry run uvicorn pingpong:server --port 8000 --workers 1 --reload
```

NOTE: in development the API uses a mock email sender that prints emails to the console rather than sending them.
Remember to check the console when you are expecting an email!

### Custom API Config

See the `config.toml` file for default configuration settings used in development.

You can use another config file if you want to customize your setup,
such as `config.local.toml` which will not be tracked:

```
CONFIG_PATH=config.local.toml poetry run python ...
```

## Frontend / UI

See the [`web/pingpong`](web/pingpong/README.md) directory for instructions.



# Production

TKTK instructions for deployment.

The prod deployment is available at `pingpong.hks.harvard.edu`.


# Repo Map
```
Outline of directories:
===
.db/            -- Directory for stashing DB data during development
.github/        -- Workflows / automation
alembic/        -- Database migrations
assets/         -- App design material
docs/           -- Documentary material
scripts/        -- One-off development / testing code
pingpong/       -- Python API code
  - authz/      -- Authorization model and related code
  - db/         -- Database adapters
  - email/      -- Email send clients
web/            -- Front-end code
  - pingpong/
    - build/    -- Artifacts generated by build commands
    - src/      -- Svelte / TS source code
      - lib/    -- Supporting library code, API clients, custom components
      - routes/ -- UI views (see SvelteKit docs for info on structure)
    - static/   -- Logos, favicons, etc


Important files:
===
./start-dev-docker.sh -- Script for starting development services in Docker
config.dev.toml       -- Config for Python API in Development
conftest.py           -- Config for pytest
docker-compose.yml    -- Base docker compose config
docker-compose.*.yml  -- Docker config overrides for different environments
loadtest.py           -- Script for load-testing with `locust`
test_config.toml      -- App config for Python tests
```
