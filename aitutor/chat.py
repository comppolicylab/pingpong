import json
import logging
import re

import openai
from slack_sdk.socket_mode.aiohttp import SocketModeClient

import aitutor.metrics as metrics

from .config import config
from .endpoint import Endpoint
from .meta import (ChatTurn, Role, load_channel_metadata,
                   save_channel_metadata, save_metadata)
from .reaction import react, unreact
from .text import ERROR
from .thread import SlackThread

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

    async def ensure_disclaimer(self, client: SocketModeClient):
        """Ensure that a disclaimer has been sent to the channel.

        Args:
            client: SocketModeClient instance
        """
        meta = await load_channel_metadata(self.thread.source_event)
        if not meta.get("disclaimer_sent", False):
            await client.web_client.chat_postMessage(
                channel=self.thread.channel,
                text=config.tutor.get_greeting(),
            )
            meta["disclaimer_sent"] = True
            await save_channel_metadata(self.thread.source_event, meta)

    async def mark_as_loading(self, client: SocketModeClient):
        """Mark the thread as loading.

        Args:
            client: SocketModeClient instance
        """
        await react(
            client,
            self.thread.source_event.get("event"),
            self.channel_config.loading_reaction,
        )

    async def mark_as_finished(self, client: SocketModeClient):
        """Mark the thread as finished loading.

        Args:
            client: SocketModeClient instance
        """
        await unreact(
            client,
            self.thread.source_event.get("event"),
            self.channel_config.loading_reaction,
        )

    def _format_content(self, turns: list[ChatTurn]) -> list[dict]:
        """Format the content of the thread for posting to Slack.

        Args:
            turns: The turns to format.

        Returns:
            The formatted content.
        """
        doc_pattern = r"\[doc(\d+)\]"
        doc_ref_labels = {}
        # Find all references to citations in the text. We want to rewrite this
        # text to use nicer citations, like [1] instead of [doc1]. We also
        # want to track specifically which citations are referenced, so if we
        # see [doc1] and [doc2], we want a set that contains {0, 1}.
        #
        # The text might also use unintuitive ordering of citations, like only
        # referencing [doc2] and [doc3]. So we also renumber the references
        # here so that they make more sense.
        text = turns[-1].content
        while True:
            match = re.search(doc_pattern, text)
            if not match:
                break
            ref = match.group(1)
            doc_idx = int(ref) - 1
            if doc_idx not in doc_ref_labels:
                doc_ref_labels[doc_idx] = len(doc_ref_labels) + 1
            label = doc_ref_labels[doc_idx]
            text = text[: match.start()] + f"[{label}]" + text[match.end() :]

        # Add the main, rewritten text to the reply.
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": text,
                },
            }
        ]

        if len(turns) > 1 and turns[-2].role == Role.TOOL:
            tool_data = json.loads(turns[-2].content)
            citations = tool_data.get("citations", [])
            if citations:
                blocks.append(
                    {
                        "type": "divider",
                    }
                )
                for i, citation in enumerate(citations):
                    # Only add docs that were referenced in the text.
                    if i not in doc_ref_labels:
                        continue
                    blocks.append(
                        {
                            "type": "context",
                            "elements": [
                                {
                                    "type": "mrkdwn",
                                    "text": f"*[{doc_ref_labels[i]}]* <{citation['url']}|{citation['filepath']}>",
                                }
                            ],
                        }
                    )

        return blocks

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

            # Try to generate a nicely-formatted version of the response. If
            # we fail, we'll fall back to the raw text.
            reply_blocks = None
            try:
                reply_blocks = self._format_content(new_turns)
            except Exception as e:
                logger.exception(e)

            # Post the response in the thread.
            await client.web_client.chat_postMessage(
                channel=self.thread.channel,
                thread_ts=self.thread.ts,
                text=new_turns[-1].content,
                blocks=reply_blocks,
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
            await save_metadata(
                {
                    "team_id": self.thread.team_id,
                    "event": {
                        "channel": self.thread.channel,
                        "ts": self.thread.ts,
                    },
                },
                {"error": str(e)},
            )
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
        new_messages, call_meta = await endpoint(
            messages=self._format_convo(), **kwargs
        )

        # Log the metadata as metrics
        metrics.engine_usage.labels(
            direction="out",
            model=endpoint.model.name,
            engine=endpoint.model.params.engine.name,
            workspace=self.thread.team_id,
            channel=self.thread.channel,
            user=self.thread.user_id,
        ).observe(call_meta.tok_out)
        metrics.engine_usage.labels(
            direction="in",
            model=endpoint.model.name,
            engine=endpoint.model.params.engine.name,
            workspace=self.thread.team_id,
            channel=self.thread.channel,
            user=self.thread.user_id,
        ).observe(call_meta.tok_in)

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
        models = self.channel_config.models
        if not models:
            raise ValueError("No models are configured.")
        switch = Endpoint(switch_model)

        # Generate model descriptions
        descriptions = "\n".join(f"` - {m.name}`: {m.description}" for m in models)

        # Generate model slugs for TypeScript string literal union
        slugs = " | ".join(f"'{m.name}'" for m in models)

        # Format examples about how to use the model into the convo.
        messages = []
        for model in models:
            for ex in model.examples:
                messages.append({"role": Role.USER, "content": ex.user})
                messages.append(
                    {
                        "role": Role.AI,
                        "content": _switch_response(model.name, ex.ai),
                    }
                )
        # Now add the most recent message in the thread.
        messages.append(
            {
                "role": Role.USER,
                "content": self.thread.history[-1].content,
            }
        )

        try:
            response, _ = await switch(
                messages=messages,
                variables={
                    "descriptions": descriptions,
                    "slugs": slugs,
                },
            )
            logger.debug(f"Switch response: {response}")
            payload = json.loads(response[-1].content)
            # NOTE: find the model within the channel_config.models, not the
            # main config, which might not be fully-specified.
            model = next(m for m in models if m.name == payload["model"])
            logger.debug(f"Selected model: {model.name}")
            return Endpoint(model)
        except Exception as e:
            logger.exception(e)
            default_model = models[0]
            logger.warning(
                "Failed to make an informed model choice. "
                f"Defaulting to {default_model.name}."
            )
            return Endpoint(default_model)

    def _format_convo(self) -> list[dict]:
        """Get the chat history as a list of messages.

        Returns:
            The chat history as a list of messages.
        """
        messages = []
        at_mention = f"<@{self.thread.bot_id}>"
        for turn in self.thread.history:
            messages.append(
                {
                    "role": turn.role,
                    # Remove at-mentions for the bot from the message content
                    "content": turn.content.replace(at_mention, "").strip(),
                }
            )

        return messages
