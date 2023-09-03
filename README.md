Stats Tutor Slack Bot
===

A Slack Bot that helps students out with class assignments and logistics.


# Development

## Required infra

TODO(jnu) document what to set up in Slack + Azure


## Setup


### Dependencies

This project uses [poetry](https://python-poetry.org/) for package management,
and Python3.11.
Install poetry, then in the root directory run:

```
poetry install
```

### Config

You will need a `config.toml` file that supplies required params from `config.py`.

TODO(jnu) document fields

### Running the app

You can start the service by running:

```
poetry run python -m statschat
```
