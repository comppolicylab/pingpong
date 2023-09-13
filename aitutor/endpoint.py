import openai

from .config import Model
from .meta import ChatTurn, Role


class ChatWithDataCompletion(openai.ChatCompletion):
    """Azure ChatCompletion with custom data sources."""

    OBJECT_NAME = "extensions.chat.completions"

    @classmethod
    def _prepare_params(cls, params: dict):
        """Prepare parameters for completion endpoint.

        This formats the `dataSources` parameter for the Cognitive Search
        endpoint in Azure, then returns a copy of the parameters that's fully
        specified (instead of the partially-specified params we allow to be
        defined in the config).

        Args:
            params: Parameters defined in the model config

        Returns:
            A copy of the parameters with `dataSources` filled in.
        """
        params = params.copy()
        cs_endpoint = params.pop("cs_endpoint")
        cs_key = params.pop("cs_key")
        index_name = params.pop("index_name")
        restrict_answers_to_data = params.pop("restrict_answers_to_data")
        semantic_configuration = params.pop("semantic_configuration")

        if "dataSources" not in params:
            system_prompt = params["messages"][0]["content"]
            params["dataSources"] = [{
                "parameters": {
                    "embeddingEndpoint": None,
                    "embeddingKey": None,
                    "endpoint": cs_endpoint,
                    "fieldsMapping": {},
                    "filter": None,
                    "indexName": index_name,
                    "inScope": restrict_answers_to_data,
                    "key": cs_key,
                    "queryType": "semantic",
                    "semanticConfiguration": semantic_configuration,
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


# Classes that are available for completion
_CLASSES = {
        c.__name__: c
        for c in [
            openai.ChatCompletion,
            ChatWithDataCompletion,
        ]}


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
            raise ValueError(f"Invalid model completion type: {model.params.completion_type}")
        self._completion_class = _CLASSES[model.params.completion_type]

    async def __call__(self, **kwargs):
        """Create a completion asynchronously.

        Args:
            **kwargs: Keyword arguments to pass to OpenAI.

        Returns:
            See `_CLASSES` return types
        """
        extra_vars = kwargs.pop("variables", {})
        params = self.model.params.dict()
        params.pop("completion_type")
        params.pop("type")
        params.update(kwargs)

        # Add a system prompt from the model config if one is not defined.
        params['messages'] = (
                self._get_model_messages(extra_vars) +
                params.get('messages', [])
                )

        response = await self._completion_class.acreate(**params)
        return self._format_response(response)

    def _get_model_messages(self, extra_vars: dict | None = None) -> list[dict]:
        """Get the chat turns that come from the model config.

        Args:
            extra_vars: Extra variables to pass to the model template

        Returns:
            A list of messages from the model config.
        """
        messages = [{
                "role": Role.SYSTEM,
                "content": self.model.get_prompt(extra_vars),
                }]
        for ex in self.model.prompt.examples:
            messages.append({
                "role": Role.USER,
                "content": ex.user,
                })
            messages.append({
                "role": Role.AI,
                "content": ex.ai,
                })
        return messages

    def _format_response(self, response: dict) -> list[ChatTurn]:
        """Format a response from OpenAI.

        Args:
            response: A response from an OpenAI endpoint.

        Returns:
            A list of ChatTurns.
        """
        first_choice = response.choices[0]
        msgs = list[dict]()
        if 'message' in first_choice:
            msgs.append(first_choice['message'])
        elif 'messages' in first_choice:
            msgs.extend(first_choice['messages'])
        else:
            raise ValueError(f"Invalid response: {response}")

        return [ChatTurn(m['role'], m['content']) for m in msgs]
