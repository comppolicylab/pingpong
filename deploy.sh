#!/usr/bin/env bash

set -e

source ./docker.env
docker login --username $PINGPONG_DOCKER_USER --password $PINGPONG_DOCKER_PW aitutor.azurecr.io

docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker push aitutor.azurecr.io/srv:latest
docker push aitutor.azurecr.io/web:latest

scp docker.env pingpong:~/
scp docker-compose.yml pingpong:~/
scp docker-compose.prod.yml pingpong:~/
scp config.prod.toml pingpong:~/
scp nginx.conf pingpong:~/
scp cert/aitutor.hks.harvard.edu.cer pingpong:~/
scp cert/aitutor.hks.harvard.edu.key pingpong:~/
ssh -T pingpong << EOF
  source ./docker.env

  sudo useradd -m -s /bin/bash pingpong || true
  sudo groupadd -f pingpong
  sudo usermod -aG pingpong pingpong

  sudo mkdir -p /opt/pingpong
  sudo mkdir -p /opt/pingpong/cert
  sudo mkdir -p /opt/pingpong/db

  sudo cp docker-compose.yml /opt/pingpong/
  sudo cp docker-compose.prod.yml /opt/pingpong/
  sudo cp config.prod.toml /opt/pingpong/
  sudo cp nginx.conf /opt/pingpong/
  sudo cp aitutor.hks.harvard.edu.cer /opt/pingpong/cert/
  sudo cp aitutor.hks.harvard.edu.key /opt/pingpong/cert/

  sudo chown -R pingpong:pingpong /opt/pingpong

  cd /opt/pingpong
  sudo systemctl start docker
  sudo docker login --username $PINGPONG_DOCKER_USER --password $PINGPONG_DOCKER_PW aitutor.azurecr.io
  sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml down
  sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
  sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml up --no-build -d
EOF
