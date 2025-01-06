FROM alpine:3.21 AS builder

RUN [ "apk", "add", "openssl" ]
RUN [ "mkdir", "/assets" ]

# Generate a self-signed certificate so that the server can run in HTTPS mode
RUN openssl req -x509 -newkey rsa:4096 -sha256 -nodes \
    -keyout /etc/ssl/pingpong-openfga-self-signed.key \
    -out /etc/ssl/pingpong-openfga-self-signed.crt \
    -days 3650 \
    -subj "/C=US/ST=MA/L=Cambridge/O=Harvard Kennedy School/OU=CPL/CN=pingpong-openfga.private"

RUN [ "chmod", "666", "/etc/ssl/pingpong-openfga-self-signed.key" ]

FROM openfga/openfga:v1.8.3

COPY --from=builder /etc/ssl/pingpong-openfga-self-signed.key /etc/ssl/pingpong-openfga-self-signed.key
COPY --from=builder /etc/ssl/pingpong-openfga-self-signed.crt /etc/ssl/pingpong-openfga-self-signed.crt

ENV OPENFGA_HTTP_TLS_ENABLED=true
ENV OPENFGA_HTTP_TLS_CERT=/etc/ssl/pingpong-openfga-self-signed.crt
ENV OPENFGA_HTTP_TLS_KEY=/etc/ssl/pingpong-openfga-self-signed.key
