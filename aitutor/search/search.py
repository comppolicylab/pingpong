from dataclasses import dataclass

import chromadb


@dataclass
class QueryResult:
    """A query result.

    Attributes:
        content: The content of the result.
        url: The URL of the result.
    """

    content: str
    url: str


def query_chroma(
    cli: chromadb.Client, name: str, s: str, n: int = 5
) -> list[QueryResult]:
    """Run a querty against the given chroma collection.

    Args:
        cli: Chroma client.
        name: Name of the collection to query.
        s: Query string.
        n: Number of closest results to return.

    Returns:
        A list of QueryResult objects.
    """
    col = cli.get_collection(name)
    results = col.query(query_texts=[s], n_results=n)
    return [
        QueryResult(
            content=results["documents"][0][i],
            url=results["metadatas"][0][i]["$path"],
        )
        for i in range(len(results["documents"][0]))
    ]
