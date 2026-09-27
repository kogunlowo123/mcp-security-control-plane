"""Metadata enricher for ingested documents."""

from __future__ import annotations

import hashlib
import time
from typing import Any


class MetadataEnricher:
    """Adds standard metadata fields to documents before storing."""

    def enrich(
        self,
        content: str,
        source_url: str = "",
        doc_type: str = "text",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a metadata dict for a document chunk.

        Args:
            content: Document text content.
            source_url: Origin URL or S3 path.
            doc_type: Document type (pdf, html, text, policy, etc.).
            extra: Additional key-value metadata to merge.

        Returns:
            Enriched metadata dictionary.
        """
        metadata: dict[str, Any] = {
            "source_url": source_url,
            "doc_type": doc_type,
            "created_at": time.time(),
            "checksum": hashlib.sha256(content.encode()).hexdigest(),
        }
        if extra:
            metadata.update(extra)
        return metadata
