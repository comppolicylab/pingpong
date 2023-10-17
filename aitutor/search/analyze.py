import os

from azure.ai.formrecognizer import AnalyzeResult, DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from PyPDF2 import PdfReader

from aitutor.cache import persist
from aitutor.config import config


def start_analyze(
    cli: DocumentAnalysisClient, fn: str, pages: str, *, model: str, locale: str
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


def analyze_cache_key(_, fn: str, **kwargs) -> str:
    """Derive a cache key from the filename and kwargs."""
    parts = [f"{k}:{str(v)}" for k, v in kwargs.items()]
    return os.path.join(*parts, fn)


@persist(
    "cache",
    key=analyze_cache_key,
    ser=lambda x: [d.to_dict() for d in x],
    de=lambda x: [AnalyzeResult.from_dict(d) for d in x],
)
def analyze_document(
    cli: DocumentAnalysisClient,
    fn: str,
    model: str = "prebuilt-layout",
    locale: str = "en-US",
) -> list[AnalyzeResult]:
    """Analyze the given document with Azure DocumentIntelligence.

    Args:
        cli: DocumentAnalysisClient
        fn: filename
        model: model to use
        locale: locale to use

    Returns:
        list of analyzed pages
    """
    page_count = len(PdfReader(fn).pages)
    pages = []
    for i in range(page_count):
        # TODO(jnu) when rate-limit is lifted, can parallelize
        poller = start_analyze(cli, fn, f"{i + 1}", model=model, locale=locale)
        pages.append(poller.result())
    return pages


def get_client(key: str, endpoint: str) -> DocumentAnalysisClient:
    """Get a DocumentAnalysisClient.

    Args:
        key: Azure API key
        endpoint: Azure API endpoint

    Returns:
        DocumentAnalysisClient
    """
    return DocumentAnalysisClient(endpoint=endpoint, credential=AzureKeyCredential(key))


def analyze(fn: str, **kwargs) -> list[AnalyzeResult]:
    """Analyze the given document with Azure DocumentIntelligence.

    Args:
        fn: filename
        **kwargs: see analyze_document

    Returns:
        list of analyzed pages
    """
    client = get_client(config.di.key, config.di.endpoint)
    return analyze_document(client, fn, **kwargs)
