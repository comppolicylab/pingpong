FROM node:21-alpine

RUN npm install -g pnpm

WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

ARG node_env=production
ARG api_proto=http
ARG api_host=srv:8000
ARG host=0.0.0.0
ARG port=3000
ARG origin=https://localhost

COPY . .
ENV VITE_SENTRY_DSN=$sentry_dsn
ENV API_PROTO=$api_proto
ENV API_HOST=$api_host
ENV NODE_ENV=$node_env
ENV HOST=$host
ENV PORT=$port
ENV ORIGIN=$origin
ENV PROTOCOL_HEADER=x-forwarded-proto
ENV HOST_HEADER=x-forwarded-host
ENV BODY_SIZE_LIMIT=512000000
RUN pnpm build

CMD ["node", "-r", "dotenv/config", "build"]
