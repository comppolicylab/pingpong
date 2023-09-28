import json
import logging
from typing import NamedTuple

import openai
import tiktoken
from async_throttle import Throttle
from openai.openai_object import OpenAIObject

from .chat_with_data_completion import ChatWithDataCompletion
from .config import Engine, Model
from .meta import ChatTurn, Role
from .metrics import engine_quota

logger = logging.getLogger(__name__)


CallMeta = NamedTuple(
    "CallMeta",
    [
        ("tok_out", int),
        ("tok_in", int),
    ],
)


# Classes that are available for completion
_CLASSES = {
    c.__name__: c
    for c in [
        openai.ChatCompletion,
        ChatWithDataCompletion,
    ]
}


class EngineImpl:
    def __init__(self, engine: Engine):
        self.engine = engine
        self._throttle = Throttle(
            engine.capacity, concurrency=engine.concurrency, period=60
        )
        self._enc = tiktoken.get_encoding(engine.encoding)

    @property
    def budget(self) -> int:
        """Get the budget for the engine."""
        return self.engine.context_size - self.engine.response_tokens

    @property
    def throttle(self) -> Throttle:
        """Get the throttle in seconds."""
        return self._throttle

    @property
    def encoder(self) -> tiktoken.Encoding:
        """Get the tokenizer."""
        return self._enc

    def num_tokens(self, text: str | ChatTurn | dict) -> int:
        """Get the number of tokens in a string."""
        if isinstance(text, str):
            return len(self._enc.encode(text))
        elif isinstance(text, ChatTurn):
            t = json.dumps(text._asdict())
            return len(self._enc.encode(t))
        else:
            t = json.dumps(text)
            return len(self._enc.encode(t))


_ENGINES = dict[str, EngineImpl]()


def get_engine(engine: Engine) -> EngineImpl:
    """Get an engine implementation.

    Args:
        engine: The engine configuration.

    Returns:
        An engine implementation.
    """
    if engine.name not in _ENGINES:
        _ENGINES[engine.name] = EngineImpl(engine)
        # Set up monitoring on this engine.
        eng = _ENGINES[engine.name]
        engine_quota.monitor(lambda: (eng.throttle.level, {"engine": engine.name}))
    return _ENGINES[engine.name]


class Endpoint:
    """A callable wrapper for a model config."""

    def __init__(self, model: Model):
        """Create a callable endpoint based on a model.

        Args:
            model: A model from the config.

        Raises:
            ValueError: If the model type is invalid.
        """
        self.model = model
        if model.params.completion_type not in _CLASSES:
            raise ValueError(
                f"Invalid model completion type: {model.params.completion_type}"
            )
        self._completion_class = _CLASSES[model.params.completion_type]

    async def __call__(self, **kwargs) -> tuple[list[ChatTurn], CallMeta]:
        """Create a completion asynchronously.

        Args:
            **kwargs: Keyword arguments to pass to OpenAI.

            List of new chat turns from the completion, as well as metadata
            about token usage.
        """
        extra_vars = kwargs.pop("variables", {})
        params = self.model.params.dict()
        params.pop("completion_type")
        params.pop("type")
        params.update(kwargs)
        params["engine"] = self.model.params.engine.name

        # Add a system prompt from the model config if one is not defined.
        params["messages"] = self._get_model_messages(extra_vars) + params.get(
            "messages", []
        )

        # Simplify the messages until it fits within the context window.
        params["messages"], tokens = self._simplify_messages(params["messages"])

        # Send requests when we have free capacity for it
        engine = get_engine(self.model.params.engine)
        logger.debug(
            f"Requesting {tokens} tokens, current capacity {engine.throttle.level}"
        )
        async with engine.throttle(tokens) as t:
            logger.debug(f"Starting completion, quota at {engine.throttle.level}")
            response = await self._completion_class.acreate(**params)
            turns = self._format_response(response)
            new_tokens = 0
            for turn in turns:
                new_tokens += engine.num_tokens(turn)
            # Anything that was returned by the model counts against the quota.
            logger.debug(
                f"Received {new_tokens} tokens, current capacity {engine.throttle.level}"
            )
            await t.consume(new_tokens)
            logger.debug(f"Finished completion, quota at {engine.throttle.level}")
            return turns, CallMeta(tok_out=tokens, tok_in=new_tokens)

    def _simplify_messages(self, messages: list[dict]) -> tuple[list[dict], int]:
        """Simplify the messages until it fits within the context window.

        Args:
            messages: A list of messages to simplify.

        Returns:
            A tuple containing the simplified messages and the number of tokens
            contained in the message.
        """
        engine = get_engine(self.model.params.engine)
        total_tokens = 0
        if not messages:
            return messages, total_tokens

        # TODO(jnu): better way of holding out number of tokens for a response.
        budget = engine.budget

        simplified = list[dict]()

        # We definitely want to include the system prompt
        simplified.append(messages[0])
        total_tokens += engine.num_tokens(messages[0])

        if len(messages) < 2:
            return simplified, total_tokens

        # Try to add as much of the latest prompt as fits
        tokens = engine.num_tokens(messages[-1])
        if tokens + total_tokens <= budget:
            simplified.append(messages[-1])
            total_tokens += tokens
        else:
            # Trim the message to fit within the budget
            # NOTE (jnu): we add 10 tokens to the budget to account for the
            # formatting. TODO - make this more precise.
            spare_tokens = budget - total_tokens - 10
            encoded = engine.encoder.encode(messages[-1])
            content = engine.encoder.decode(encoded[:spare_tokens])
            simplified.append(
                {
                    "role": messages[-1]["role"],
                    "content": content,
                }
            )
            total_tokens += len(encoded)

        # For the rest of the messages, work backwards and add as many messages
        # as we can fit in the window.
        for msg in reversed(messages[1:-1]):
            tokens = engine.num_tokens(msg)
            spare_tokens = budget - total_tokens
            if tokens <= spare_tokens:
                # Insert the message after the system prompt
                simplified.insert(1, msg)
                total_tokens += tokens
            else:
                # TODO(jnu): try to trim the message to fit within the budget.
                # This is tricky with TOOL messages which can be very lengthy
                # and are stored as JSON.
                break

        return simplified, total_tokens

    def _get_model_messages(self, extra_vars: dict | None = None) -> list[dict]:
        """Get the chat turns that come from the model config.

        Args:
            extra_vars: Extra variables to pass to the model template

        Returns:
            A list of messages from the model config.
        """
        messages = [
            {
                "role": Role.SYSTEM,
                "content": self.model.get_prompt(extra_vars),
            }
        ]
        for ex in self.model.prompt.examples:
            messages.append(
                {
                    "role": Role.USER,
                    "content": ex.user,
                }
            )
            messages.append(
                {
                    "role": Role.AI,
                    "content": ex.ai,
                }
            )
        return messages

    def _format_response(self, response: OpenAIObject) -> list[ChatTurn]:
        """Format a response from OpenAI.

        Args:
            response: A response from an OpenAI endpoint.

        Returns:
            A list of ChatTurns.
        """
        first_choice = response.choices[0]
        msgs = list[dict]()
        if "message" in first_choice:
            msgs.append(first_choice["message"])
        elif "messages" in first_choice:
            msgs.extend(first_choice["messages"])
        else:
            raise ValueError(f"Invalid response: {response}")

        return [ChatTurn(m["role"], m["content"]) for m in msgs]
