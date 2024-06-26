SAML Configurations
===

This directory contains SAML configurations (along with certificates) for different providers.

Each provider is in a subdirectory, such as `saml/harvardkey`.

An example directory structure is:

```
saml/
saml/harvardkey/
saml/harvardkey/settings.json
saml/harvardkey/advanced_settings.json
saml/harvardkey/certs/.gitkeep

# The following are not checked into git:
saml/harvardkey/certs/sp.key
saml/harvardkey/certs/sp.crt
saml/harvardkey/certs/metadata.key
saml/harvardkey/certs/metadata.crt
```

### Certificates

Certs are not checked into the git repo, but a placeholder directory should be created for them and checked in.

In production, certificates should be added to these directories as needed from the appropriate secrets manager.
