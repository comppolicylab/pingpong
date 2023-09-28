import openai


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
            params["dataSources"] = [
                {
                    "parameters": {
                        "embeddingEndpoint": None,
                        "embeddingKey": None,
                        "endpoint": cs_endpoint,
                        "fieldsMapping": {},
                        # document how it needs to be set up in the index!
                        #   "contentFields": [
                        #       "content"
                        #   ],
                        #   "contentFieldsSeparator": "\n",
                        #   "filepathField": "filepath",
                        # These are two custom fields we have added to enrich
                        # the documents in the index with the original source
                        # document link, *not* the Azure storage link! This
                        # way the bot will seem to be more directly integrated
                        # with the course documents (on Canvas, Github, etc).
                        #   "titleField": "simple_name",
                        #   "urlField": "original_link",
                        #   "vectorFields": []
                        # },
                        "filter": None,
                        "indexName": index_name,
                        "inScope": restrict_answers_to_data,
                        "key": cs_key,
                        "queryType": "semantic",
                        "semanticConfiguration": semantic_configuration,
                        "roleInformation": system_prompt,
                    },
                    "type": "AzureCognitiveSearch",
                }
            ]

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
