FROM node:21-alpine

RUN npm install -g pnpm

WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

ARG node_env=production
ARG api_host=srv:8000
ARG host=0.0.0.0
ARG port=3000

COPY . .
ENV API_HOST=$api_host
ENV NODE_ENV=$node_env
ENV HOST=$host
ENV PORT=$port
ENV ORIGIN=http://localhost
ENV PROTOCOL_HEADER=x-forwarded-proto
ENV HOST_HEADER=x-forwarded-host
RUN pnpm build

EXPOSE $port

CMD ["node", "-r", "dotenv/config", "build"]
