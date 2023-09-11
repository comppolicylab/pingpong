from datetime import datetime
import logging
import json

import openai
from slack_sdk.socket_mode.aiohttp import SocketModeClient

from .endpoint import Endpoint
from .thread import SlackThread, ChatTurn, Role
from .config import config
from .meta import (
        save_metadata,
        load_channel_metadata,
        save_channel_metadata,
        )
from .reaction import react, unreact
from .text import SWITCH_PROMPT


logger = logging.getLogger(__name__)


# Configure OpenAI with values from config
openai.api_type = config.azure.oai.api.type
openai.api_base = config.azure.oai.api.base
openai.api_key = config.azure.oai.api.key
openai.api_version = config.azure.oai.api.chat_version


class AiChat:

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

    async def reply(self, client: SocketModeClient):
        """Reply to the thread.

        Args:
            client: SocketModeClient instance
        """
        await self.ensure_disclaimer(client)
        await self.mark_as_loading(client)
        try:
            new_turns = await self.generate_next_turn(Role.AI, self.prompt)

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
                    text=f"An error occurred: {e}",
                    )
            await save_metadata({
                'team_id': self.thread.team_id,
                'event': {
                    'channel': self.thread.channel,
                    'ts': self.thread.ts,
                    },
            }, {'error': str(e)})
        await self.mark_as_finished(client)

    async def generate_next_turn(self, **kwargs) -> list[ChatTurn]:
        """Generate the next reply.

        Args:
            **kwargs: Additional keyword arguments to pass to OpenAI.

        Returns:
            The system's response.
        """
        endpoint = await self.choose_endpoint()
        response = await endpoint(messages=self._format_convo(), **kwargs)

        new_messages = list[ChatTurn]()
        for msg in response.choices[0].messages:
            self.thread.add_message(msg['role'], msg['content'])
            new_messages.append(self.thread.history[-1])

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

        # TODO format few-shot examples into the prompt
        messages = [{"role": Role.SYSTEM, "content": prompt}]

        try:
            response = await switch(messages=messages)
            logger.debug(f"Switch response: {response}")
            payload = json.loads(response.choices[0].messages[-1]['content'])
            model = next(m for m in models if m.name == payload['model'])
            logger.debug(f"Selected model: {model.name}")
            return Endpoint(model)
        except Exception as e:
            logger.exception(e)
            default_model = models[0]
            logger.warning(f"Failed to make an informed model choice. Defaulting to {default_model.name}.")
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
        history = ex_turns + self.threads.history

        at_mention = f"<@{self.bot_id}>"
        for turn in history:
            messages.append({
                "role": turn.role,
                # Remove at-mentions for the bot from the message content
                "content": turn.content.replace(at_mention, "").strip(),
                })

        return messages
