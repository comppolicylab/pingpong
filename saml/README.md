SAML Configurations
===

This directory contains SAML configurations (along with certificates) for different providers.

Each provider is in a subdirectory, such as `saml/harvardkey`.

An example directory structure is:

```
saml/
saml/harvardkey/
saml/harvardkey/settings.json
saml/harvardkey/fields.json
saml/harvardkey/certs/.gitkeep

# The following are not checked into git:
saml/harvardkey/certs/sp.key
saml/harvardkey/certs/sp.crt
saml/harvardkey/certs/metadata.key
saml/harvardkey/certs/metadata.crt
```

### Settings

The `settings.json` file mostly needs to match the IdP's requirements and the SP metadata registered with the IdP.

### Fields

The `fields.json` file is a mapping between human readable names and attributes sent by the IdP.

For example:

```json
{
    "email": "urn:oid:0.9.2342.19200300.100.1.3",
    "lastName": "urn:oid:2.5.4.4",
    "middleName": "urn:oid:1.3.6.1.4.1.6341.610.1.2.1.300",
    "firstName": "urn:oid:2.5.4.42",
    "name": "urn:oid:2.16.840.1.113730.3.1.241"
}
```


### Certificates

Certs are not checked into the git repo, but a placeholder directory should be created for them and checked in.

In production, certificates should be added to these directories as needed from the appropriate secrets manager.
