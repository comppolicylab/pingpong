#!/usr/bin/env bash

set -e

# Run migrations on the production server
ssh -T pingpong << EOF
  cd /opt/pingpong
  sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml pull srv
  sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml run srv poetry run python -m pingpong db migrate
EOF
