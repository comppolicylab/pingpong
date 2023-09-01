from typing import NamedTuple
import openai

from config import config


# Configure OpenAI with values from config
openai.api_type = config.azure.oai.api.type
openai.api_base = config.azure.oai.api.base
openai.api_key = config.azure.oai.api.key
openai.api_version = config.azure.oai.api.version


ChatTurn = NamedTuple('ChatTurn', [('user', str), ('ai', str)])


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

    def chat(self, text: str, **kwargs) -> str:
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
        response = openai.Completion.create(**settings)
        message = response.choices[0].message
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

