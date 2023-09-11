import openai

from .config import Model


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
        if model.type not in _CLASSES:
            raise ValueError(f"Invalid model type: {model.type}")
        self._completion_class = _CLASSES[model.type]

    async def __call__(self, **kwargs):
        """Create a completion asynchronously.

        Args:
            **kwargs: Keyword arguments to pass to OpenAI.

        Returns:
            See `_CLASSES` return types
        """
        params = self.model.params._asdict()
        params.update(kwargs)
        return await self._completion_class.acreate(**params)
