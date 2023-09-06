#!/bin/sh
docker run -d -it --rm --name aitutor --mount type=bind,source="$(pwd)"/config.toml,target=/code/config.toml,readonly --mount type=bind,source="$(pwd)"/db,target=/db aitutor:latest
