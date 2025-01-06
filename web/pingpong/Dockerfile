FROM node:21-alpine AS buildweb

RUN npm install -g pnpm

WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

ARG node_env=production
ARG host=0.0.0.0
ARG port=3000
ARG origin=https://localhost

COPY ./src ./src
COPY ./static ./static
COPY postcss.config.cjs svelte.config.js tailwind.config.js tsconfig.json vite.config.ts ./
ENV VITE_SENTRY_DSN=$sentry_dsn
ENV NODE_ENV=$node_env
ENV HOST=$host
ENV PORT=$port
ENV ORIGIN=$origin
ENV PROTOCOL_HEADER=x-forwarded-proto
ENV HOST_HEADER=x-forwarded-host
ENV BODY_SIZE_LIMIT=512000000
RUN pnpm build -d


# Production image is just nginx with assets copied in
FROM nginx:1.27.0

RUN apt-get update && apt-get install ca-certificates -y && update-ca-certificates

ARG host=0.0.0.0
ARG port=3000
ARG ssl_port=3001

RUN openssl req -trustout -x509 -newkey rsa:4096 -sha256 -nodes \
    -keyout /etc/ssl/private/pingpong-self-signed.key \
    -out /etc/ssl/certs/pingpong-self-signed.crt \
    -days 3650 \
    -subj "/C=US/ST=MA/L=Cambridge/O=Harvard Kennedy School/OU=CPL/CN=pingpong-web.private"

ENV NGINX_LISTEN=$host:$port
ENV NGINX_LISTEN_SSL=$host:$ssl_port
ENV NGINX_SSL_CERT=/etc/ssl/certs/pingpong-self-signed.crt
ENV NGINX_SSL_CERT_KEY=/etc/ssl/private/pingpong-self-signed.key

COPY default.conf.template /etc/nginx/templates/
COPY --from=buildweb /app/build /usr/share/nginx/html
