import chromadb
import openai
import logging
import re
from dataclasses import dataclass
import click
import openai.resources
from typing import Callable
from chromadb.utils import embedding_functions
from sklearn import cluster

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


@dataclass
class SimpleMessage:
    id: str
    text: str


Chunker = Callable[[SimpleMessage], list[str]]


# TODO better embedding function
default_embedder = embedding_functions.DefaultEmbeddingFunction()


def default_chunker(message: SimpleMessage) -> list[str]:
    # TODO implement a more sophisticated chunker
    # This just splits on newlines and periods, which is often not great.
    return [chunk for chunk in re.split(r"\n|\. ", message.text) if chunk]


def simplify_message(
    message: openai.resources.beta.threads.messages.Message,
) -> SimpleMessage:
    text = ""
    for part in message.content:
        if part.type == "text":
            text += part.text.value
        else:
            # TODO multimodal support
            logger.debug("Ignoring non-text part of message")
    return SimpleMessage(id=message.id, text=text)


def get_thread_user_messages(oai: openai.OpenAI, thread_id: str) -> list[SimpleMessage]:
    logger.debug(f"Loading user messages for thread {thread_id} ...")
    messages = list[SimpleMessage]()
    # TODO filtering by date range
    new_messages = oai.beta.threads.messages.list(thread_id=thread_id)
    while True:
        for message in new_messages:
            if message.role == "user":
                messages.append(simplify_message(message))
        if new_messages.has_next_page():
            new_messages = new_messages.get_next_page()
        else:
            break
    return messages


def get_all_user_messages(
    oai: openai.OpenAI, thread_ids: list[str]
) -> list[SimpleMessage]:
    messages = list[SimpleMessage]()
    for thread_id in thread_ids:
        logger.debug(f"Loading messages for thread {thread_id} ...")
        messages += get_thread_user_messages(oai, thread_id)
    return messages


def ingest_message(
    collection: chromadb.Collection,
    message: SimpleMessage,
    chunker: Chunker = default_chunker,
):
    if not message.text:
        return
    chunks = chunker(message)
    collection.add(
        documents=chunks,
        ids=[f"{message.id}-{i}" for i in range(len(chunks))],
    )


def cluster_embeddings(collection: chromadb.Collection, k: int = 2) -> cluster.KMeans:
    # TODO we don't really need chroma...
    embeddings = collection.peek(limit=0)["embeddings"]
    km = cluster.KMeans(n_clusters=k)
    km.fit(embeddings)
    return km


def get_representative_chunks(
    collection: chromadb.Collection, clusters: cluster.KMeans, n: int = 1
) -> list[str]:
    chunks = list[str]()
    for center in clusters.cluster_centers_:
        result = collection.query(center, n_results=n)
        chunks += result["documents"][0]
    return chunks


def reduce_messages(messages: list[SimpleMessage], k: int = 2, n: int = 1) -> list[str]:
    vdb = chromadb.Client()
    message_vectors = vdb.create_collection(
        name="messages", embedding_function=default_embedder
    )

    for message in messages:
        ingest_message(message_vectors, message)

    km = cluster_embeddings(message_vectors, k=k)
    chunks = get_representative_chunks(message_vectors, km, n=n)

    logger.debug("Representative chunks:")
    for chunk in chunks:
        logger.debug(f" - {chunk}")

    return chunks


def generate_summary(oai: openai.OpenAI, chunks: list[str]) -> str:
    logger.debug("Generating summary...")
    summary = oai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": "You are a meta-assistant that summarizes the input given to you. You will be given a list of excerpts from different conversations that have happened. You should return a short summary of common themes from these conversations. Do NOT answer any of the snippets in the list directly, just summarize them.",
            },
            {
                "role": "user",
                "content": "Find common themes in the following:\n\n"
                + "\n - ".join(chunks),
            },
        ],
    )
    response = summary.choices[0].message
    return response.content or "<failed to generate summary>"


@click.group()
def cli():
    pass


@cli.command("stdin")
@click.option("--clusters", help="Number of clusters to use", default=2)
def check_input(clusters: int):
    """Find representative chunks from standard input."""
    messages = list[SimpleMessage]()
    for line in click.get_text_stream("stdin"):
        messages.append(SimpleMessage(id=str(len(messages)), text=line))
    reduce_messages(messages, k=clusters)


@cli.command("threads")
@click.option("--thread-ids", help="List of thread IDs to summarize")
@click.option("--api-key", help="OpenAI API key")
@click.option("--clusters", help="Number of clusters to use", default=2)
@click.option(
    "--samples", help="Number of samples to take from each cluster", default=1
)
def summarize_threads(thread_ids: str, api_key: str, clusters: int, samples: int):
    """Generate a summary of messages from a list of threads."""
    oai = openai.OpenAI(api_key=api_key)

    messages = get_all_user_messages(oai, thread_ids.split(","))
    logger.debug(f"Loaded {len(messages)} user messages")

    chunks = reduce_messages(messages, k=clusters, n=samples)

    summary = generate_summary(oai, chunks)
    print(summary)


if __name__ == "__main__":
    cli()
