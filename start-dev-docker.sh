#!/usr/bin/env bash

set -e

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
docker compose -f docker-compose.yml -f docker-compose.dev.yml run authz migrate

# Init the Pingpong db stuff
docker compose -f docker-compose.yml -f docker-compose.dev.yml build srv
docker compose -f docker-compose.yml -f docker-compose.dev.yml run srv poetry run python -m pingpong db init

# Run the app
docker compose -f docker-compose.yml -f docker-compose.dev.yml up authz srv -d
