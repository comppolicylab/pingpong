#!/usr/bin/env bash

set -e

echo "Setting up the PingPong development environment..."

# Make sure the services are down to begin with
docker compose -f docker-compose.yml -f docker-compose.dev.yml down

# Start the database
docker compose -f docker-compose.yml -f docker-compose.dev.yml up db -d

# Wait until postgres is ready
until docker exec pingpong-db pg_isready
do
  echo "Waiting for postgres to start..."
  sleep 1
done

# Wait until the pingpong database is ready
until docker exec pingpong-db psql -Upingpong -c '\l'
do
  echo "Waiting for pingpong database to be ready..."
  sleep 1
done

# Make sure that the database `authz` schema exists in postgres db
docker exec pingpong-db psql -Upingpong -c "CREATE SCHEMA IF NOT EXISTS authz;"

# Run the OpenFGA migrate command to init the database
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm authz migrate

# Update the PingPong srv image
docker compose -f docker-compose.yml -f docker-compose.dev.yml build srv

# Init/update the PingPong DB. It's ok if the DB already exists - in that
# case the init command does not do anything. We will apply migrations to
# put the DB in the correct state.
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm srv uv run --no-dev python -m pingpong db init
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm srv uv run --no-dev python -m pingpong db migrate

# Run the app
docker compose -f docker-compose.yml -f docker-compose.dev.yml up authz srv -d

# Wait until the authz server is ready
# The healthcheck command is `/usr/local/bin/grpc_health_probe -addr=authz:8081`
until docker exec pingpong-authz /usr/local/bin/grpc_health_probe -addr=authz:8081
do
  echo "Waiting for authz server to start..."
  sleep 1
done

# Wait until the pingpong server is ready
# The healthcheck command is `curl -f http://localhost:8000/health`
until docker exec pingpong-srv-1 curl -fs http://localhost:8000/health
do
  echo "Waiting for pingpong server to start..."
  sleep 1
done

echo ""
echo "All services are ready! 🏓"
