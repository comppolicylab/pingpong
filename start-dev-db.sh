#!/usr/bin/env bash

set -e

mkdir -p .db/pg

# Start the database
docker compose -f docker-compose.yml -f docker-compose.dev.yml up db -d
