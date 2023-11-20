import hashlib
import logging
import os
import uuid

from azure.ai.formrecognizer import AnalyzeResult, DocumentAnalysisClient
from chromadb import Client, Collection

from aitutor.search import analyze_document

logger = logging.getLogger(__name__)


HASH = "$hash"
PATH = "$path"
TITLE = "$title"


def _get_hash(s: str) -> str:
    """Get hex for the SHA-256 hash of a string.

    Args:
        s: String to hash

    Returns:
        Hex digest of hashed string
    """
    h = hashlib.sha256()
    h.update(s.encode("utf-8"))
    return h.hexdigest()


def _compute_doc_hash(path: str, linesize: int = 4096) -> str:
    """Compute the checksum of a document.

    Args:
        path: Path to a document
        linesize: Number of bytes to read in each chunk

    Returns:
        Hex digest of hashed doc
    """
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while b := fh.read(linesize):
            h.update(b)
    return h.hexdigest()


def _add_doc_to_collection(
    collection: Collection, adoc: AnalyzeResult, metadata: dict[str, str] | None = None
):
    """Add the analysis result into the given collection.

    Args:
        collection: The ChromaDB collection to use
        adoc: AnalysisResult from Azure DocumentIntelligence
        metadata: Any additional metadata to add to document
    """
    docs = list[str]()
    metas = list[dict[str, str]]()
    ids = list[str]()
    doc = ""
    title = ""

    def save_current_segment():
        if not doc:
            return
        docs.append(doc)
        meta = {}
        if metadata:
            meta.update(metadata)
        meta.update({TITLE: title})
        metas.append(meta)
        # Use a stable ID if possible, otherwise just a random UUID.
        if HASH in meta and PATH in meta:
            id_ = _get_hash(f"{meta[HASH]}:meta[PATH]:{len(ids)}")
        else:
            id_ = str(uuid.uuid4())
        ids.append(id_)

    # For every page in the doc, loop through text regions and try to assemble
    # them into logical segments based on the title/sectionHeading annotations.
    # TODO(jnu): there are other pieces of semantic info that we can parse.
    for x in adoc:
        for p in x.paragraphs:
            if p.role == "title" or p.role == "sectionHeading":
                if doc:
                    save_current_segment()
                if p.role == "title":
                    title = p.content
                doc = p.content
                continue

            doc += "\n" + p.content
    if doc:
        save_current_segment()

    collection.add(documents=docs, metadatas=metas, ids=ids)


def ingest(
    di_client: DocumentAnalysisClient,
    collection: Collection,
    path: str,
    metadata: dict[str, str] | None = None,
):
    """Parse a document and add it to the collection.

    Args:
        di_client: Azure DocumentIntelligence client
        collection: ChromaDB collection
        path: Path to document
        metadata: Any additional metadata to add to document
    """
    # Check if document is in the index already based on path and content hash.
    # If the document has changed at all, it will be removed and re-added.
    dochash = _compute_doc_hash(path)
    docfilter = {PATH: path, HASH: dochash}
    existing = collection.get(where={PATH: path})["metadatas"]
    if not existing or existing[0][HASH] != dochash:
        if existing:
            logger.debug(
                "File {path} is indexed but has been modified, so re-analyzing"
            )
            # Ensure cached version of analysis is removed so it can be re-run.
            analyze_document.evict(di_client, path)
        else:
            logger.debug("Adding new file at {path} to index")
        analyze_result = analyze_document(di_client, path)
        # Remove any existing document at the path to re-add it.
        collection.delete(where={PATH: path})
        meta = {}
        if metadata:
            meta.update(metadata)
        meta.update(docfilter)
        _add_doc_to_collection(collection, analyze_result, metadata=meta)
    else:
        logger.debug(f"File {path} is already indexed and unmodified")
    return dochash


def ingest_folder(
    di_client: DocumentAnalysisClient,
    collection: Collection,
    directory: str,
    metadata: dict[str, str] | None = None,
):
    """Ingest all files in a folder recursively.

    Args:
        di_client: Azure DocumentIntelligence client
        collection: ChromaDB collection
        directory: Root directory to ingest
        metadata: Any additional metadata to add to document
    """
    logger.info(
        f"Scanning {directory} to ingest documents, this may take some time ..."
    )
    supported_exts = {".pdf"}
    experimental_exts = {
        ".html",
        ".txt",
        ".docx",
        ".doc",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".png",
        ".jpeg",
        ".jpg",
        ".bmp",
        ".tiff",
    }
    ingested = set[str]()
    for root, _, files in os.walk(directory):
        bn = os.path.basename(root)
        if bn.startswith("."):
            logger.info(f"Ignoring hidden directory {root}")
            continue
        for f in files:
            _, ext = os.path.splitext(f)
            if ext.lower() not in supported_exts | experimental_exts:
                logger.warning(f"Unsupported filetype: {ext}")
                continue
            if ext.lower() in experimental_exts:
                logger.warning(f"Analyzing {ext} file with experimental support")
            path = os.path.join(root, f)
            logger.info(f"Ingesting {path} ...")
            dochash = ingest(di_client, collection, path, metadata=metadata)
            ingested.add(dochash)
    logger.info(f"Finished! Ingested {len(ingested)} document(s).")
    return ingested


def ensure_search_index(
    cdb_client: Client,
    di_client: DocumentAnalysisClient,
    name: str,
    directories: list[str],
) -> Collection:
    """Ensure collection exists and all documents are synced.

    Args:
        cdb_client: ChromaDB client
        di_client: Azure DocumentIntelligence client
        name: Name of the collection
        directories: List of directories to sync
    """
    col = cdb_client.get_or_create_collection(name=name)
    all_docs = set[str]()
    deleted_docs = set[str]()
    for d in directories:
        all_docs |= ingest_folder(di_client, col, d)
    # Find docs that are in the index but were not ingested
    for m in col.get()["metadatas"]:
        h = m[HASH]
        if h not in all_docs:
            deleted_docs.add(h)
    # Now prune the index to remove deleted docs
    if deleted_docs:
        logger.info(f"Pruning index of {len(deleted_docs)} deleted document(s) ...")
        for d in deleted_docs:
            col.delete(where={HASH: d})
    return col
