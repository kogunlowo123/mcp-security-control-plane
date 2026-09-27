"""Recursive character-based text chunker backed by LangChain's splitter."""

from __future__ import annotations

from typing import List, Optional

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

from .base import BaseChunker


class RecursiveChunker(BaseChunker):
    """Splits text using LangChain's :class:`RecursiveCharacterTextSplitter`.

    The splitter tries each separator in *separators* in order, recursing on
    the resulting pieces until every piece is at most *chunk_size* characters
    long.  Adjacent pieces overlap by *chunk_overlap* characters to preserve
    sentence context across chunk boundaries.

    This is the default chunker for the ingestion pipeline and works well for
    most plain-text and policy documents.

    Args:
        chunk_size:    Maximum character length of each chunk (default 512).
        chunk_overlap: Number of characters shared between consecutive chunks
                       (default 64).
        separators:    Ordered list of separator strings tried in priority
                       order.  Falls back to empty string (hard split) last.
    """

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        separators: Optional[List[str]] = None,
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or ["\n\n", "\n", ". ", "! ", "? ", " ", ""]

        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=self.separators,
            length_function=len,
            is_separator_regex=False,
        )

    def chunk(self, text: str, metadata: dict) -> List[Document]:
        """Split *text* and return one :class:`Document` per chunk.

        Each document's metadata is a shallow copy of *metadata* augmented with:

        * ``chunk_index``  — zero-based position in this document's chunk list.
        * ``chunk_count``  — total number of chunks produced from this text.
        * ``chunker``      — ``"recursive"`` (for provenance tracking).
        """
        if not text or not text.strip():
            return []

        raw_chunks = self._splitter.split_text(text)
        total = len(raw_chunks)
        documents: List[Document] = []

        for idx, chunk_text in enumerate(raw_chunks):
            chunk_text = chunk_text.strip()
            if not chunk_text:
                continue

            chunk_meta = dict(metadata)
            chunk_meta["chunk_index"] = idx
            chunk_meta["chunk_count"] = total
            chunk_meta["chunker"] = "recursive"
            documents.append(Document(page_content=chunk_text, metadata=chunk_meta))

        return documents
