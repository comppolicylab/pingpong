Certificates
===
The certs here are for development only. Production secrets are not checked into the repo.

The tracked files look like this:

```
- cert/
  - DevRootCA.crt
  - DevRootCA.key
  - DevRootCA.pem
  - DevRootCA.srl
  - dev.crt
  - dev.csr
  - dev.key
  - domains.ext
```

## Dev Certificate Authority

The fake certificate authority keys are checked in as `DevRootCA.*` files.

This was generated with the following commands:

```
openssl req -x509 -nodes -new -sha256 -days 3650 -newkey rsa:2048 -keyout cert/DevRootCA.key -out cert/DevRootCA.pem -subj "/C=US/CN=PingPong-Dev-Root-CA"
openssl x509 -outform pem -in cert/DevRootCA.pem -out cert/DevRootCA.crt
```

The CA uses the `cert/domains.ext` file to describe covered domains.

## Dev certificate

The development certificate for `pingpong.local` was generated with these commands:

```
# Generate a signing request for the fake CA
openssl req -new -nodes -newkey rsa:2048 -keyout cert/dev.key -out cert/dev.csr -subj "/C=US/ST=MA/L=Cambridge/O=Harvard Kennedy School/CN=pingpong.local"

# Generate the certificate from the CSR
openssl x509 -req -sha256 -days 3650 -in cert/dev.csr -CA cert/DevRootCA.pem -CAkey cert/DevRootCA.key -CAcreateserial -extfile cert/domains.ext -out cert/dev.crt
```
