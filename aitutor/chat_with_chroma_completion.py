import json

import chromadb
import openai

from .search import query_chroma


class ChatWithChromaCompletion(openai.ChatCompletion):
    """Chat with ChromaDB augmentation."""

    @classmethod
    def _prepare_params(cls, params: dict):
        params = params.copy()
        top_n = params.pop("topNDocuments")
        params.pop("dirs")
        collection_name = params.pop("collection")

        db = chromadb.PersistentClient()
        q = params["messages"][-1]["content"]
        results = query_chroma(db, collection_name, q, n=top_n)
        ctx = [r["content"] for r in results]
        addendum = (
            "\n\nUse the following context to help answer the question:\n"
            f"{json.dumps(ctx)}"
        )
        params["messages"][-1]["content"] += addendum
        return params

    @classmethod
    async def acreate(cls, **kwargs):
        params = cls._prepare_params(kwargs)
        return await super().acreate(**params)

    @classmethod
    def create(cls, **kwargs):
        params = cls._prepare_params(kwargs)
        return super().create(**params)
