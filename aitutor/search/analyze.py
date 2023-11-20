import json
import os
from functools import partial

from azure.ai.formrecognizer import AnalyzeResult, DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from PyPDF2 import PdfReader
from PyPDF2.errors import PdfReadError

from aitutor.cache import get_local_db, persist

_CACHE_DIR = partial(get_local_db, "azure-di")


def start_analyze(
    cli: DocumentAnalysisClient,
    fn: str,
    pages: str | None = None,
    *,
    model: str,
    locale: str,
):
    """Start analyzing the given document with Azure DocumentIntelligence.

    Args:
        cli: DocumentAnalysisClient
        fn: filename
        pages: pages to analyze
        model: model to use
        locale: locale to use
    """
    with open(fn, "rb") as fh:
        return cli.begin_analyze_document(
            model, document=fh, locale=locale, pages=pages
        )


def analyze_cache_key(
    cli: DocumentAnalysisClient,
    fn: str,
    **kwargs,
) -> str:
    """Derive a cache key from the filename and kwargs."""
    parts = [f"{k}:{str(v)}" for k, v in kwargs.items()]
    return os.path.join(*parts, fn)


def ser_analyze_result(x: list[AnalyzeResult]) -> str:
    """Serialize an AnalyzeResult."""
    return json.dumps([d.to_dict() for d in x])


def des_analyze_result(x: str) -> list[AnalyzeResult]:
    """Deserialize an AnalyzeResult."""
    return [AnalyzeResult.from_dict(d) for d in json.loads(x)]


@persist(
    _CACHE_DIR,
    key=analyze_cache_key,
    ser=ser_analyze_result,
    de=des_analyze_result,
)
def analyze_document(
    cli: DocumentAnalysisClient,
    fn: str,
    **kwargs,
) -> list[AnalyzeResult]:
    """Analyze the given document with Azure DocumentIntelligence.

    Args:
        cli: DocumentAnalysisClient
        fn: filename
        model: model to use
        locale: locale to use
        parallelism: Number of pages to process simultaneously

    Returns:
        list of analyzed pages
    """
    model = kwargs.get("model", "prebuilt-layout")
    locale = kwargs.get("locale", "en-US")
    parallelism = kwargs.get("parallelism", 2)

    # For PDFs we need to process pages individually. PDF is probably also the
    # most common input type. So try to treat everything as a PDF to start,
    # then fall back to reading the whole document if that fails (because the
    # file is not actually a PDF).
    # TODO - more robust support for non-PDF types, e.g. using LC chunkers.
    is_pdf = True
    try:
        page_count = len(PdfReader(fn).pages)
        pages = [None] * page_count
    except PdfReadError:
        page_count = 1
        pages = [None]
        is_pdf = False
    pending = []
    for i in range(page_count):
        if is_pdf:
            poller = start_analyze(
                cli, fn, pages=f"{i + 1}", model=model, locale=locale
            )
        else:
            # The prebuilt-layout model doesn't non-PDF format, so if the model
            # was left as the default, replace it.
            model = "prebuilt-read" if model == "prebuilt-layout" else model
            poller = start_analyze(cli, fn, model=model, locale=locale)
        pending.append((i, poller))
        # Block until pending queue is cleared. This isn't perfectly
        # efficient (since some requests might take longer than others,
        # so we will end up blocking while the batch finishes even though
        # we have spare capacity).
        #
        # Can rewrite a more efficient solution with threads if desired.
        if parallelism >= 0 and len(pending) >= parallelism:
            while pending:
                i, p = pending.pop(0)
                pages[i] = poller.result()
    # Block waiting for results of the rest of the pollers.
    for pend in pending:
        i, p = pend
        pages[i] = p.result()
    return pages


def get_analysis_client(key: str, endpoint: str) -> DocumentAnalysisClient:
    """Get a DocumentAnalysisClient.

    Args:
        key: Azure API key
        endpoint: Azure API endpoint

    Returns:
        DocumentAnalysisClient
    """
    return DocumentAnalysisClient(endpoint=endpoint, credential=AzureKeyCredential(key))
