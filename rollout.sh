#!/usr/bin/env bash

set -e

# Get deployment name from CLI; it is the first argument
DEPLOYMENT_NAME=$1

# Run the rollout command for the given DEPLOYMENT_NAME on the remote machine.
ssh -T pingpong << EOF
  cd /opt/pingpong
  sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml pull $DEPLOYMENT_NAME
  sudo docker rollout -f docker-compose.yml -f docker-compose.prod.yml $DEPLOYMENT_NAME
EOF
