![PingPong](assets/owl@256px.png)

PingPong
===

A web app that helps students out with class assignments and logistics.


# Development

## Running locally

You can run the Python API and the front-end live-reload dev server locally:

### Database
The following command starts a Postgres DB in Docker with a persistent volume:

```
docker compose -f docker-compose.yml -f docker-compose.dev.yml up db
```

Of course, you can run postgres15 another way if you choose.
We also support a SQLite backend if needed,
although since prod uses Postgres it's best to use this in dev as well!


### Backend / API

We use `Python 3.11` and [`Poetry`](https://python-poetry.org/) for package management.

Run `poetry install --with dev` to install dependencies.

The following command runs the API in development mode:
```
poetry run uvicorn pingpong:server --port 8000 --workers 1 --reload
```

NOTE: in development the API uses a mock email sender that prints emails to the console rather than sending them.
Remember to check the console when you are expecting an email!

#### Custom Config
See the `config.toml` file for default configuration settings used in development.

You can use another config file if you want to customize your setup,
such as `config.local.toml` which will not be tracked:

```
CONFIG_PATH=config.local.toml poetry run python ...
```


### Frontend / UI

See the [`web/pingpong`](`web/pingpong/README.md`) directory for instructions.


## Docker Compose

We use docker containers for deployment.
You can test this locally as well (useful for checking networking, TLS, etc):

Bring up all docker services in development mode:
```
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

This will serve the site on `https://pingpong.local`.
You should add the following line to your `/etc/hosts` file to resolve it to localhost:
```
127.0.0.1   pingpong.local
```


### SSL

The dev `docker-compose` cluster uses a certificate signed by our local authority.

**In order to stop receiving security alerts while developing, you need to trust this authority!**
To do so, in your browser's security settings, import the `cert/DevRootCA.crt` file.
Then you can use `https://pingpong.localhost` without issue.


The (obviously insecure) dev CA and keys are checked into the repo in plaintext.
See [cert/README.md](the cert directory) for more information.

To use a real certificate in production, just override the `webcrt` and `webkey` secrets with the appropriate files.


# Production

Use the `./deploy.sh` and `./rollout.sh` scripts for deployment.
TKTK this will change soon!

The prod deployment is available at `pingpong.hks.harvard.edu`.
