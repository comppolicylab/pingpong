from typing import NamedTuple
import openai

from config import config


# Configure OpenAI with values from config
openai.api_type = config.azure.oai.api.type
openai.api_base = config.azure.oai.api.base
openai.api_key = config.azure.oai.api.key
openai.api_version = config.azure.oai.api.chat_version


ChatTurn = NamedTuple('ChatTurn', [('user', str), ('ai', str)])


class ChatWithDataCompletion(openai.ChatCompletion):
    """Azure ChatCompletion with custom data sources."""

    OBJECT_NAME = "extensions.chat.completions"

    @classmethod
    def _prepare_params(cls, params):
        params = params.copy()
        if "dataSources" not in params:
            system_prompt = params["messages"][0]["content"]
            params["dataSources"] = [{
                "parameters": {
                    "embeddingEndpoint": None,
                    "embeddingKey": None,
                    "endpoint": config.azure.cs.endpoint,
                    "fieldsMapping": {
                        "contentFields": [
                            "content"
                        ],
                        "contentFieldsSeparator": "\n",
                        "filepathField": None,
                        "titleField": "title",
                        "urlField": None,
                        "vectorFields": []
                    },
                    "filter": None,
                    "indexName": config.azure.cs.index_name,
                    "inScope": True,
                    "key": config.azure.cs.key,
                    "queryType": "semantic",
                    "roleInformation": system_prompt,
                    "semanticConfiguration": "default",
                },
                "type": "AzureCognitiveSearch"
            }]
        return params

    @classmethod
    async def acreate(cls, **kwargs):
        """Create a completion asynchronously with data sources.

        Args:
            **kwargs: Keyword arguments to pass to OpenAI.

        Returns:
            A completion with data sources.
        """
        params = cls._prepare_params(kwargs)
        return await super().acreate(**params)

    @classmethod
    def create(cls, **kwargs):
        """Create a completion with data sources.

        Args:
            **kwargs: Keyword arguments to pass to OpenAI.

        Returns:
            A completion with data sources.
        """
        params = cls._prepare_params(kwargs)
        return super().create(**params)


class Chat:

    def __init__(self, system_prompt: str):
        self.system_prompt = system_prompt
        self.history = list[ChatTurn]()

    def add_example(self, user: str, ai: str):
        """Add an example to the chat history.

        Args:
            user: The user's message.
            ai: The AI's response.
        """
        self.history.append(ChatTurn(user, ai))

    async def chat(self, text: str, **kwargs) -> str:
        """Chat with the system.

        Args:
            text: The user's message.
            **kwargs: Additional keyword arguments to pass to OpenAI.

        Returns:
            The system's response.
        """
        settings = dict(
                engine=config.azure.oai.engine,
                messages=self._get_messages(text),
                temperature=config.azure.oai.temperature,
                top_p=config.azure.oai.top_p,
                **kwargs,
                )
        response = await ChatWithDataCompletion.acreate(**settings)
        message = response.choices[0].messages[-1]
        self.add_example(text, message['content'])
        return message['content']

    def _get_messages(self, text: str) -> list[dict]:
        """Get the chat history as a list of messages.

        Args:
            text: The user's message.

        Returns:
            The chat history as a list of messages.
        """
        messages = [{
            "role": "system",
            "content": self.system_prompt,
            }]

        for turn in self.history:
            messages.append({
                "role": "user",
                "content": turn.user,
                })
            messages.append({
                "role": "assistant",
                "content": turn.ai,
                })

        messages.append({
            "role": "user",
            "content": text,
            })

        return messages
