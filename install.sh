#!/usr/bin/env bash

# Install the poetry dependencies
poetry install

# Ensure that the aitutor user exists
useradd -r -s /bin/false aitutor

# Make sure that the /opt/aitutor directory exists
mkdir -p /opt/aitutor

# Link the python module to the /opt/aitutor directory
ln -s $(pwd)/statschat /opt/aitutor/statschat

# Copy the aitutor.sh shell script to the /opt/aitutor directory
cp aitutor.sh /opt/aitutor/aitutor.sh

# Copy the config.toml file to the /opt/aitutor directory
cp config.toml /opt/aitutor/config.toml

# Transfer ownership of the /opt/aitutor directory to the aitutor user
chown -R aitutor:aitutor /opt/aitutor

# Mark the aitutor.sh shell script as executable
chmod 555 /opt/aitutor/aitutor.sh
# Config file should be readable by all
chmod 444 /opt/aitutor/config.toml

# Copy the aitutor.service systemd unit file to the /etc/systemd/system directory
cp aitutor.service /etc/systemd/system/aitutor.service

# Reload the systemd daemon
systemctl daemon-reload

# Enable the aitutor.service systemd unit file
systemctl enable aitutor.service

# Start the aitutor.service systemd unit file
systemctl start aitutor.service

