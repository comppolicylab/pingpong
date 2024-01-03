#!/usr/bin/env bash

set -e

source ./docker.env
docker login --username $AITUTOR_DOCKER_USER --password $AITUTOR_DOCKER_PW aitutor.azurecr.io

docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker push aitutor.azurecr.io/srv:latest
docker push aitutor.azurecr.io/web:latest

scp docker.env aitutor:~/
scp docker-compose.yml aitutor:~/
scp docker-compose.prod.yml aitutor:~/
scp config.prod.toml aitutor:~/
scp nginx.conf aitutor:~/
scp cert/aitutor.hks.harvard.edu.cer aitutor:~/
scp cert/aitutor.hks.harvard.edu.key aitutor:~/
ssh -T aitutor << EOF
  source ./docker.env

  sudo useradd -m -s /bin/bash aitutor || true
  sudo groupadd -f aitutor
  sudo usermod -aG aitutor aitutor

  sudo mkdir -p /opt/aitutor
  sudo mkdir -p /opt/aitutor/cert
  sudo mkdir -p /opt/aitutor/db

  sudo cp docker-compose.yml /opt/aitutor/
  sudo cp docker-compose.prod.yml /opt/aitutor/
  sudo cp config.prod.toml /opt/aitutor/
  sudo cp nginx.conf /opt/aitutor/
  sudo cp aitutor.hks.harvard.edu.cer /opt/aitutor/cert/
  sudo cp aitutor.hks.harvard.edu.key /opt/aitutor/cert/

  sudo chown -R aitutor:aitutor /opt/aitutor

  cd /opt/aitutor
  sudo systemctl start docker
  sudo docker login --username $AITUTOR_DOCKER_USER --password $AITUTOR_DOCKER_PW aitutor.azurecr.io
  sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml down
  sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
  sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml up --no-build -d
EOF
