#!/usr/bin/env bash

set -e

# Get deployment name from CLI; it is the first argument
DEPLOYMENT_NAME=$1

# Bail if no deployment name is given
if [ -z "$DEPLOYMENT_NAME" ]; then
  echo "No deployment name given."
  exit 1
fi

# Bail if deployment is not `srv` or `web`
if [ "$DEPLOYMENT_NAME" != "srv" ] && [ "$DEPLOYMENT_NAME" != "web" ]; then
  echo "Deployment name must be 'srv' or 'web'."
  exit 1
fi

# Run the rollout command for the given DEPLOYMENT_NAME on the remote machine.
ssh -T pingpong << EOF
  cd /opt/pingpong
  sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml pull $DEPLOYMENT_NAME
  sudo docker rollout -f docker-compose.yml -f docker-compose.prod.yml $DEPLOYMENT_NAME
EOF
