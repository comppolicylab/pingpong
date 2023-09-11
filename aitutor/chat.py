from datetime import datetime
import logging
import json

import openai
from slack_sdk.socket_mode.aiohttp import SocketModeClient

from .endpoint import Endpoint
from .thread import SlackThread
from .config import config
from .meta import (
        save_metadata,
        load_channel_metadata,
        save_channel_metadata,
        ChatTurn,
        Role,
        )
from .reaction import react, unreact
from .text import SWITCH_PROMPT, ERROR


logger = logging.getLogger(__name__)


# Configure OpenAI with values from config
# TODO - may need to scope this per request
openai.api_type = config.openai.api_type
openai.api_base = config.openai.api_base
openai.api_key = config.openai.api_key
openai.api_version = config.openai.api_version


def _switch_response(name: str, reason: str) -> str:
    """Format one of the example AI responses for the switch model.

    Args:
        name: The name of the model to switch to.
        reason: The reason for the switch.

    Returns:
        The formatted response.
    """
    return """\
{{
  "intent": {reasons},
  "model": {name}
}}\
""".format(
        reasons=json.dumps([reason]),
        name=json.dumps(name),
        )


class AiChat:
    """Wrapper for the SlackThread that adds AI response capabilities."""

    def __init__(self, thread: SlackThread):
        self.thread = thread
        self.channel_config = config.get_channel(thread.team_id, thread.channel)
        # Get the channel configuration
        self.prompt = self.channel_config.prompt.system.format(
                # Today's date as a string like Wednesday, December 4, 2019.
                date=datetime.today().strftime("%A, %B %d, %Y"),
                focus=self.channel_config.prompt.focus,
                )

    async def ensure_disclaimer(self, client: SocketModeClient):
        """Ensure that a disclaimer has been sent to the channel.

        Args:
            client: SocketModeClient instance
        """
        meta = await load_channel_metadata(self.thread.source_event)
        if not meta.get('disclaimer_sent', False):
            await client.web_client.chat_postMessage(
                    channel=self.thread.channel,
                    text=config.tutor.greeting.format(
                        focus=self.channel_config.prompt.focus),
                    )
            meta['disclaimer_sent'] = True
            await save_channel_metadata(self.thread.source_event, meta)

    async def mark_as_loading(self, client: SocketModeClient):
        """Mark the thread as loading.

        Args:
            client: SocketModeClient instance
        """
        await react(client,
                    self.thread.source_event.get('event'),
                    self.channel_config.loading_reaction)

    async def mark_as_finished(self, client: SocketModeClient):
        """Mark the thread as finished loading.

        Args:
            client: SocketModeClient instance
        """
        await unreact(client,
                      self.thread.source_event.get('event'),
                      self.channel_config.loading_reaction)

    async def reply(self, client: SocketModeClient, **kwargs):
        """Reply to the thread.

        This method doesn't return anything; instead it performs IO both
        to post to Slack and to save metadata in our own stores.

        The `thread` object that this instance wraps will be updated to reflect
        the new state of the conversation.

        Args:
            client: SocketModeClient instance
            **kwargs: Additional keyword arguments to pass to OpenAI.
        """
        await self.ensure_disclaimer(client)
        await self.mark_as_loading(client)
        try:
            new_turns = await self.generate_next_turn(**kwargs)

            # Post the response in the thread.
            await client.web_client.chat_postMessage(
                    channel=self.thread.channel,
                    thread_ts=self.thread.ts,
                    text=new_turns[-1].content,
                    )

            # Save metadata
            if len(new_turns) > 1:
                await save_metadata(self.thread.source_event, new_turns[:-1])
        except Exception as e:
            logger.exception(e)
            await client.web_client.chat_postMessage(
                    channel=self.thread.channel,
                    text=ERROR,
                    )
            await save_metadata({
                'team_id': self.thread.team_id,
                'event': {
                    'channel': self.thread.channel,
                    'ts': self.thread.ts,
                    },
            }, {'error': str(e)})
        await self.thread.save()
        await self.mark_as_finished(client)

    async def generate_next_turn(self, **kwargs) -> list[ChatTurn]:
        """Generate the next reply.

        Args:
            **kwargs: Additional keyword arguments to pass to OpenAI.

        Returns:
            The system's response.
        """
        endpoint = await self.choose_endpoint()
        new_messages = await endpoint(messages=self._format_convo(), **kwargs)

        # Add the new messages to the thread
        for msg in new_messages:
            self.thread.add_message(*msg)

        return new_messages

    async def choose_endpoint(self) -> Endpoint:
        """Choose the endpoint to use for the next turn.

        Returns:
            The endpoint to use for the next turn.

        Raises:
            ValueError: If no models are configured.
        """
        switch_model = config.get_model(config.tutor.switch_model)
        models = [m for m in config.models if m.name != switch_model.name]
        if not models:
            raise ValueError("No models are configured.")
        switch = Endpoint(switch_model)

        # Generate model descriptions
        descriptions = "\n".join(
                f"` - {m.name}`: {m.description}"
                for m in models
                )

        # Generate model slugs for TypeScript string literal union
        slugs = " | ".join(
                f"'{m.name}'"
                for m in models
                )

        # Generate prompt
        prompt = SWITCH_PROMPT.format(
                descriptions=descriptions,
                slugs=slugs,
                )
        logger.debug(f"Switch Prompt: {prompt}")

        # Format the switch prompt along with examples that were provided
        # in the config about how to use each model.
        messages = [{"role": Role.SYSTEM, "content": prompt}]
        for model in models:
            for ex in model.examples:
                messages.append({"role": Role.USER, "content": ex.user})
                messages.append({
                    "role": Role.AI,
                    "content": _switch_response(model.name, ex.ai),
                    })
        # Now add the most recent message in the thread.
        messages.append({
            "role": Role.USER,
            "content": self.thread.history[-1].content,
            })

        try:
            response = await switch(messages=messages)
            logger.debug(f"Switch response: {response}")
            payload = json.loads(response[-1].content)
            model = next(m for m in models if m.name == payload['model'])
            logger.debug(f"Selected model: {model.name}")
            return Endpoint(model)
        except Exception as e:
            logger.exception(e)
            default_model = models[0]
            logger.warning(
                    "Failed to make an informed model choice. "
                    f"Defaulting to {default_model.name}.")
            return Endpoint(default_model)

    def _format_convo(self) -> list[dict]:
        """Get the chat history as a list of messages.

        Returns:
            The chat history as a list of messages.
        """
        messages = [{
            "role": Role.SYSTEM,
            "content": self.prompt,
            }]

        examples = self.channel_config.prompt.examples
        ex_turns = list[ChatTurn]()
        for example in examples:
            ex_turns.append(ChatTurn(Role.USER, example.user))
            ex_turns.append(ChatTurn(Role.AI, example.ai))
        history = ex_turns + self.thread.history

        at_mention = f"<@{self.thread.bot_id}>"
        for turn in history:
            messages.append({
                "role": turn.role,
                # Remove at-mentions for the bot from the message content
                "content": turn.content.replace(at_mention, "").strip(),
                })

        return messages
