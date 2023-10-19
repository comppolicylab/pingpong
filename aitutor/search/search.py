import chromadb


def query_chroma(cli: chromadb.Client, name: str, s: str, n: int = 5):
    col = cli.get_collection(name)
    results = col.query(query_texts=[s], n_results=n)
    return [
        {
            "content": results["documents"][0][i],
            "url": results["metadatas"][0][i],
        }
        for i in range(len(results["documents"][0]))
    ]
