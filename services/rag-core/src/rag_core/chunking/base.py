"""Abstract base class for all chunkers."""

from abc import ABC, abstractmethod
from typing import List

from langchain_core.documents import Document


class BaseChunker(ABC):
    """Defines the interface all chunker implementations must satisfy.

    A chunker takes a raw text string plus the metadata dict from its source
    document and returns a list of :class:`~langchain_core.documents.Document`
    objects — one per logical chunk — each inheriting a copy of that metadata
    augmented with chunk-specific fields such as ``chunk_index``.
    """

    @abstractmethod
    def chunk(self, text: str, metadata: dict) -> List[Document]:
        """Split *text* into chunks and return one Document per chunk.

        Args:
            text:     The raw text content to split.
            metadata: Metadata dict from the parent document; **must not** be
                      mutated in place — copy it before adding chunk fields.

        Returns:
            Ordered list of :class:`Document` objects.  Returns an empty list
            when *text* is empty or whitespace-only.
        """
        ...
