from typing import NamedTuple
import openai

from .config import config


# Configure OpenAI with values from config
openai.api_type = config.azure.oai.api.type
openai.api_base = config.azure.oai.api.base
openai.api_key = config.azure.oai.api.key
openai.api_version = config.azure.oai.api.chat_version


class Role:
    """Roles for chat participants."""

    USER = "user"
    AI = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


ChatTurn = NamedTuple('ChatTurn', [('role', str), ('content', str)])


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
                            "content",
                            "title",
                        ],
                        "contentFieldsSeparator": "\n",
                        "filepathField": None,
                        "titleField": "title",
                        "urlField": None,
                        "vectorFields": []
                    },
                    "filter": None,
                    "indexName": params.pop("index_name"),
                    "inScope": config.azure.cs.restrict_answers_to_data,
                    "key": config.azure.cs.key,
                    # "queryType": "simple",
                    "queryType": "semantic",
                    "semanticConfiguration": "default",
                    "roleInformation": system_prompt,
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
        from pprint import pprint
        print("\n\n===PARAMS===")
        pprint(params)
        print("============\n\n")
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

    def __init__(self,
                 bot_id: str,
                 system_prompt: str,
                 index_name: str,
                 examples: list[dict] = None):
        self.system_prompt = system_prompt
        self.index_name = index_name
        self.history = list[ChatTurn]()
        self.bot_id = bot_id
        if examples:
            for example in examples:
                self.add_message(example['role'], example['content'])

    def __iter__(self):
        """Iterate over the chat history."""
        return iter(self.history)

    def is_relevant(self) -> bool:
        """Check if the chat is relevant to the bot.

        Returns:
            True if the chat is relevant, False otherwise.
        """
        at_mention = f"<@{self.bot_id}>"
        for turn in self.history:
            if turn.role == Role.USER and at_mention in turn.content:
                return True
        return False

    def add_message(self, role: str, text: str):
        """Add a message to the chat history.

        Args:
            role: The role of the message sender.
            text: The message text.
        """
        last_message = self.history[-1] if self.history else None
        # Append to the last message if it was sent by the same role.
        # The language model seems to focus on the most recent USER message,
        # so make sure it has full context.
        # TODO(jnu): There might be multiple parties in the conversation, and
        # I'm not sure whether to try to model this here or not.
        if last_message and last_message.role == role:
            new_text = last_message.content + '\n' + text
            self.history[-1] = ChatTurn(role, new_text)
        else:
            self.history.append(ChatTurn(role, text))

    async def reply(self, **kwargs) -> list[ChatTurn]:
        """Generate the next reply.

        Args:
            **kwargs: Additional keyword arguments to pass to OpenAI.

        Returns:
            The system's response.
        """
        settings = dict(
                index_name=self.index_name,
                engine=config.azure.oai.engine,
                messages=self._get_messages(),
                temperature=config.azure.oai.temperature,
                top_p=config.azure.oai.top_p,
                **kwargs,
                )
        response = await ChatWithDataCompletion.acreate(**settings)
        new_messages = list[ChatTurn]()
        for msg in response.choices[0].messages:
            self.add_message(msg['role'], msg['content'])
            new_messages.append(self.history[-1])
        return new_messages

    def _get_messages(self) -> list[dict]:
        """Get the chat history as a list of messages.

        Returns:
            The chat history as a list of messages.
        """
        messages = [{
            "role": Role.SYSTEM,
            "content": self.system_prompt,
            }]

        at_mention = f"<@{self.bot_id}>"
        for turn in self.history:
            messages.append({
                "role": turn.role,
                # Remove at-mentions for the bot from the message content
                "content": turn.content.replace(at_mention, "").strip(),
                })

        return messages
