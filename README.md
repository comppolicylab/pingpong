![PingPong](assets/owl@256px.png) PingPong
===

A web app that helps students out with class assignments and logistics.


# Development

## Building locally

TKTK

## Docker Compose

Bring up all docker services:
```
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

This will make the site available on `https://pingpong.localhost`.


### SSL

The dev `docker-compose` cluster uses a certificate signed by our local authority.

**In order to stop receiving security alerts while developing, you need to trust this authority!**
To do so, in your browser's security settings, import the `cert/DevRootCA.crt` file.
Then you can use `https://pingpong.localhost` without issue.


In order to

The (obviously insecure) dev CA and keys are checked into the repo in plaintext.
See [cert/README.md](the cert directory) for more information.
