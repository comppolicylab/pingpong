#!/usr/bin/env bash

# Ensure that the aitutor user exists
useradd -r -s /bin/false aitutor

curl -sSL https://install.python-poetry.org | sudo -u aitutor python3 -

# Make sure that the /opt/aitutor directory exists
mkdir -p /opt/aitutor
mkdir -p /opt/aitutor/db

cp aitutor.sh /opt/aitutor/aitutor.sh

# Copy the config.toml and other project files to the /opt/aitutor directory
cp config.toml /opt/aitutor/config.toml

# Transfer ownership of the /opt/aitutor directory to the aitutor user
chown -R aitutor:aitutor /opt/aitutor

# Mark the aitutor.sh shell script as executable
chmod 555 /opt/aitutor/aitutor.sh
# Config file and other project files should be readable by all
chmod 444 /opt/aitutor/config.toml
# DB directory should allow RW
chown -R aitutor:aitutor /opt/aitutor/db
chmod -R 775 /opt/aitutor/db

# Copy the aitutor.service systemd unit file to the /etc/systemd/system directory
cp aitutor.service /etc/systemd/system/aitutor.service

# Reload the systemd daemon
systemctl daemon-reload

# Enable the aitutor.service systemd unit file
systemctl enable aitutor.service

# Start the aitutor.service systemd unit file
systemctl start aitutor.service

