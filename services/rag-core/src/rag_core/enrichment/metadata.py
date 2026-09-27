"""MetadataEnricher — adds standard provenance fields to documents."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from langchain_core.documents import Document

_EXT_TO_TYPE: dict = {
    ".pdf": "pdf",
    ".html": "html",
    ".htm": "html",
    ".txt": "text",
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".csv": "csv",
    ".xml": "xml",
}

_INGESTION_VERSION = "1.0"


class MetadataEnricher:
    """Adds ``source``, ``created_at``, ``doc_type``, and ``ingestion_version``
    to a document's metadata.

    Fields already present in the document's metadata are **never overwritten**
    so that values set by a loader take precedence.

    Usage::

        enricher = MetadataEnricher()
        doc = enricher.enrich(doc, source="s3://bucket/policy.pdf")
    """

    def enrich(
        self,
        doc: Document,
        source: Optional[str] = None,
        doc_type: Optional[str] = None,
    ) -> Document:
        """Return a new Document with enriched metadata.

        Args:
            doc:      Input document.
            source:   Source identifier (file path, S3 key, URL).  Only
                      applied when ``metadata["source"]`` is absent.
            doc_type: Explicit document type string.  When omitted the type
                      is inferred from the source extension.

        Returns:
            New :class:`Document` with a copy of the original metadata plus
            the enriched fields.
        """
        metadata = dict(doc.metadata)

        # source
        if source and not metadata.get("source"):
            metadata["source"] = source

        # created_at
        if not metadata.get("created_at"):
            metadata["created_at"] = datetime.now(timezone.utc).isoformat()

        # doc_type
        if not metadata.get("doc_type"):
            if doc_type:
                metadata["doc_type"] = doc_type
            else:
                src: str = metadata.get("source", "")
                ext = Path(src).suffix.lower()
                metadata["doc_type"] = _EXT_TO_TYPE.get(ext, "unknown")

        # ingestion_version
        if not metadata.get("ingestion_version"):
            metadata["ingestion_version"] = _INGESTION_VERSION

        return Document(page_content=doc.page_content, metadata=metadata)
