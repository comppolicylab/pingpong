AI Tutor Slack Bot
===

A Slack Bot that helps students out with class assignments and logistics.

# Usage

The Slack Bot only interacts with threads where it has been @-messaged in the channel where it has been configured.

To ask a question, simply @-mention the bot in the channel where you've added it. The bot will consider as much of the context in a single conversation thread as it is able, so you can keep replying within a thread. The bot does _not_ share context between threads, and it does not see other messages in the channel if it has not been @-mentioned.

You can downvote answers within threads by reacting with the `:-1:` 👎 emoji. This will make the message invisible to the bot. You can use this to flag messages the bot generates that are irrelevant, or messages written by you or other humans that are unhelpful. The bot will ignore these messages as you continue your conversation.

# Setup

## Overview

You will need to set up the following services:

 - **Slack App / Socket mode** Create a Slack App in the Slack developer console and enable "Socket Mode." In addition, you will need to request the correct scopes (listed below).
 - **Azure OpenAI** As of Sept 2023, you need to apply for access to this service within the Azure Portal. After getting that access, you need to apply for GPT-4 access as well. After getting approved for OpenAI with GPT-4, create a new OpenAI service in a region where GPT-4 is available (`East US 2` is currently a good option for North America, but this may change). Then, deploy the GPT-4 model in this region, in addition to a GPT-3.5 model (see config for details).
 - **Azure Blob Storage** Set up a blob storage container to hold documents for cognitive search. Add any documents that are relevant to the class that you want to be indexed for search (e.g., syllabi, assignments, readings). You can set downgrade the service tier to Locally Redundant Storage (default is more expensive).
 - **Azure Cognitive Search** Set up a new search service in the same region as the OpenAI service. You will (probably) need to use the `Basic` pricing tier; be careful to set this correctly, as the default tier (`Standard`) is much more expensive and probably unnecessary.
 - **Azure Semantic Search** Enable Semantic Search in the `Free` tier under your Cognitive Search deployment.
 - **Azure Search Index / Indexer** Set up an index within the cognitive search deployment based on your blob storage documents. Then, set up an indexer to process these documents. You can put this on a schedule if you are updating your documents dynamically; running the indexer on demand is also fine. Just make sure to remember to run it when you update documents! The index should have `title` and `content` fields, and you should add a Semantic Configuration called `default` with the corresponding title/content configuration.


### Slack App Scopes

First, enable Event subscriptions.

Then, request the following bot events (which will in turn automatically add scopes for your bot):
 - `app_mention` When the bot is @-mentioned
 - `link_shared` Not currently used, but may be followed in the future
 - `message.channels` Enables listening to messages in a public channel
 - `message.groups` Enables listening to messages in a private channel
 - `message.im` Enable listening to DMs
 - `message.mpim` Enable listening to multi-party DMs
 - `reaction_added` Enable interpretting new reactions
 - `reaction_removed` Enable interpretting removed reactions

Lastly, you will need additional OAuth scopes for posting to Slack:
 - `chat:write`
 - `groups:write`
 - `im:write`
 - `mpim:write`
 - `reactions:write`


### Additional Slack App Integration Configuration

You will need to request to install your Slack App into your workspace.
After you do this, take note of the Workspace ID. You can find this in the URL on the Slack Developer page for managing that workspace. The ID begins with `T`, like `TABC123XYZ9`. This will be your `team_id` you need to list in the config.
You will also need the channel ID for _each channel you want to add the bot to_. You can find this in Slack by copying a the link to the channel in the context menu and pulling out the ID that starts with `C`, like `C00ABC1230`.

### Config file

You will need a `config.toml` file that supplies required params from `config.py`.

The config file will be loaded from the path specified in the `CONFIG_PATH` environment variable. By default this is `config.toml` (i.e., the file is expected to be in the working directory).

| Field | Description | Default | Example |
| ----- | ----------- | ------- | ------- |
| `slack.app_id` | The Slack App ID from the developer console | _None_ | `A000ABC987X` |
| `slack.client_id` | From the Slack developer console | _None_ | `111111111111.9870009877890` |
| `slack.client_secret` | From the Slack developer console | _None_ | `a123a123a000bcde000123aaa` |
| `slack.signing_secret` | From the Slack developer console | _None_ | `aaa123bbb234ccc456090909` |
| `slack.web_token` | Available when your Slack App is installed in a workspace in the developer console | _None_ | `xoxb-000123000987-000123123999-abcdefghijkl` |
| `slack.socket_token` | Available when you enable socket mode on your app | _None_ | `xapp-1-AXXXXQQQTTTPPP-123412323-abcdef123456abcdef12345abcdef12343abcdef12233` |
| `openai.api_base` | The URL to the OpenAI deployment | _None_ | `https://ai-tutor.openai.azure.com/` |
| `openai.api_type` | The type of API endpoint we're using | `azure` | `azure` |
| `openai.api_version` | The API version to use | _None_ | `2023-06-01-preview` |
| `openai.api_key` | The Azure OpenAI key | _None_ | `aaa111222333abcabc123abc987` |
| `models[].name` | Name to use for the model | _None_ | `general` |
| `models[].description` | Description of the model, which will be used to classify inputs and select this model for answering questions | _None_ | `A general-purpose language model that can answer most questions` |
| `models[].prompt.system` | System prompt for the LLM. | _None_ | `You are a friendly chat bot named $name.` |
| `models[].prompt.examples[]` | List of example responses to use for few-shot tuning. | `[]` | `{ user = "what is your name?", ai = "Glen" }` |
| `models[].prompt.variables` | Variables to inject into the prompt template. | `{}` | `{ name = "glen" }` |
| `models[].params.type` | `llm` for general models, `csm` for cognitive search | _None_ | `llm` |
| `models[].params.engine` | The name of your Azure OpenAI GPT-4 deployment | _None_ | `stats-tutor-gpt4` |
| `models[].params.temperature` | The temperature setting for the LLM | `0.2` | `0.2` |
| `models[].params.top_p` | The `top_p` setting for the LLM | `0.95` | `0.95` |
| `models[].params.examples[]` | Example model classifications | `[]` | `[{ user = "Where is class?", ai = "question about course logistics" }]` |
| `models[].params.cs_endpoint` | The Cognitive Search endpoint URL (for `csm` only) | _None_ | `https://stats-tutor-cs.search.windows.net` |
| `models[].params.cs_key` | The Cognitive Search key (for `csm` only) | _None_ | `AAA111xxxxyyyAAAA111YYYdddDDDddDDDdD09` |
| `models[].params.restrict_answers_to_data` | Whether to answer strictly in terms of documents in store. `false` will let the model draw on its training to function more like a general-purpose ChatGPT. (for `csm` only) | `true` | `false` |
| `models[].params.index_name` | Cognitive search index name to use for semantic search (for `csm` only) | _None_ | `cs-aitutor-idx` |
| `sentry.dsn` | (Optional) Sentry DSN for error reporting | _None_ | `https://aaabbbcccdddeeefff000111222@o111111.ingest.sentry.io/0001112223334445555` |
| `tutor.db_dir` | Directory where local app data can be cached | `.db/` | `/cache/statstutor` |
| `tutor.loading_reaction` | Default loading emoji to post as a reaction | `thinking_face` | `thinking_face` |
| `tutor.variables` | Common variables to inject into templates | `{}` | `{ name = "glen" }` |
| `tutor.greeting` | Message to send when bot responds for the very first time in the channel. | _See text.py_ | `"Hi, I'm a friendly bot!"` |
| `tutor.models[]` | Default list of `models` available in this workspace. Can either be string names or dicts with a `name` key that override values in the model. | _None_ | `["general"]` |
| `tutor.workspaces[].models[]` | Overrides `tutor.models[]` | `[]` | `[ "general", "my-class" ]` |
| `tutor.workspaces[].team_id` | Workspace (team) ID from Slack where bot will be integrated | _None_ | `T000AAAZZZ` |
| `tutor.workspaces[].loading_reaction` | Override for inherited `loading_reaction`. | `thinking_face` | `thinking_face` |
| `tutor.workspaces[].channels[].channel_id` | Channel in the Workspace where Slack bot will be integrated | _None_ | `C000AAAZZZ` |
| `tutor.workspaces[].channels[].loading_reaction` | Override for inherited `loading_reaction`. | `thinking_face` | `dancing_robot` |
| `tutor.workspaces[].channels[].models[]` | Overrides `tutor.workspaces[].models[]` | `[]` | `[ "general", "my-class" ]` |

#### `models[]` settings

You will need to deploy at least two models in Azure OpenAI, then describe them here.

One model must be called `switch` and it should use GPT-3.5. Configure it like this:

```
[[models]]
name = "switch"
description = "Triage requests to the appropriate model."
[models.params]
type = "llm"
engine = "ai-tutor-switch"
temperature = 0.0
```

This model will be used to direct input to one of the other models.

You will also probably want at least one GPT-4 deployment to answer general questions,
and a CognitiveSearch model to answer additional questions.

You should define a `[models.prompt]` section with the system prompt here.
These (and the `params`) values can be overridden for a specific workspace / channel.


#### `tutor.workspaces[]` and `.channels[]` settings

You _must_ set the `tutor.models[]` list to provide default models available for use.
Optionally, you can override which models are available on a per-workspace and per-channel basis.


## Local development

### Dependencies

This project uses [poetry](https://python-poetry.org/) for package management,
and Python3.11.
Install poetry, then in the root directory run:

```
poetry install
```

### Running the app

You can start the service locally by running:

```
poetry run python -m aitutor
```

## Deployment

### Bare metal

You can run the Python script directly on a server. You should install dependencies with Poetry with the virtual environment setting disabled `POETRY_VIRTUALENVS_CREATE=false`.

To run, use the command `CONFIG_PATH=/path/to/config.toml python3 -m aitutor` from the code directory.

### Docker

A `Dockerfile` is provided in this container to build the image in a container.

To run the image, use something like the following command:

```
docker build . -t aitutor:latest
docker run \
    -d -it --rm \
    --name aitutor \
    --mount type=bind,source=/path/to/config.toml,target=/code/config.toml,readonly \
    --mount type=bind,source=/path/to/db/dir,target=/db \
    aitutor:latest
```

The `/path/to/config.toml` should point to the config file (see above).
and the `/path/to/db/dir` should be some existing directory on the machine where data can be persisted (doesn't really matter where this is located, but this will improve bot behavior across container restarts).

You might need additional bind mounts, depending on what your config file says.
For example, you can supply your own prompts in a custom directory and mount it into the container.

# About

This project was developed by the [Computational Policy Lab](https://policylab.stanford.edu/).

Maintainer / dev contact: [Joe Nudell](https://github.com/jnu).

Code is available under the MIT License. See [LICENSE](LICENSE) for more information.
