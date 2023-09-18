#!/usr/bin/env bash

# Ensure that the aitutor user exists
useradd -r -s /bin/false aitutor

# Make sure that the /opt/aitutor directory exists
mkdir -p /opt/aitutor
mkdir -p /opt/aitutor/db

# Transfer ownership of the /opt/aitutor directory to the aitutor user
chown -R aitutor:aitutor /opt/aitutor

# DB directory should allow RW
chown -R aitutor:aitutor /opt/aitutor/db
chmod -R 775 /opt/aitutor/db
