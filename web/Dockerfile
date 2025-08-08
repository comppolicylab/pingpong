########## Build pingpong ##########
FROM node:21-alpine AS build_pingpong

RUN npm install -g pnpm

WORKDIR /app/pingpong
COPY pingpong/package.json pingpong/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

ARG node_env=production
ARG host=0.0.0.0
ARG port=3000
ARG origin=https://localhost

COPY pingpong/src ./src
COPY pingpong/static ./static
COPY pingpong/postcss.config.cjs pingpong/svelte.config.js pingpong/tailwind.config.js pingpong/tsconfig.json pingpong/vite.config.ts ./
ENV VITE_SENTRY_DSN=$sentry_dsn
ENV NODE_ENV=$node_env
ENV HOST=$host
ENV PORT=$port
ENV ORIGIN=$origin
ENV PROTOCOL_HEADER=x-forwarded-proto
ENV HOST_HEADER=x-forwarded-host
ENV BODY_SIZE_LIMIT=512000000
RUN pnpm build -d

########## Build study ##########
FROM node:21-alpine AS build_study

RUN npm install -g pnpm

WORKDIR /app/study
COPY study/package.json study/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY study/src ./src
COPY study/static ./static
COPY study/components.json study/eslint.config.js study/svelte.config.js study/tsconfig.json study/vite.config.ts ./
RUN pnpm build

########## Final Nginx image with both sites ##########
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

# Use the nginx template stored at repo web/ level
COPY default.conf.template /etc/nginx/templates/

# Copy both build outputs into distinct roots
COPY --from=build_pingpong /app/pingpong/build /usr/share/nginx/html/pingpong
COPY --from=build_study   /app/study/build   /usr/share/nginx/html/study
