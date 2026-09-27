"""Abstract base class for all vector store backends."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.documents import Document


class VectorStore(ABC):
    """Defines the interface that pgvector and OpenSearch stores must satisfy.

    A vector store supports two core operations:

    * **upsert** — persist a batch of documents (with optional pre-computed
      embeddings) into the store, overwriting any existing document with the
      same identity.
    * **search** — given a query embedding vector, return the most similar
      documents along with their similarity scores.
    """

    @abstractmethod
    def upsert(
        self,
        docs: List[Document],
        embeddings: Optional[List[List[float]]] = None,
    ) -> None:
        """Insert or update documents in the store.

        Args:
            docs:       Batch of :class:`~langchain_core.documents.Document`
                        objects to persist.
            embeddings: Pre-computed embedding vectors aligned with *docs*.
                        When ``None``, the store implementation is responsible
                        for computing them.  Stores that require pre-computed
                        vectors (e.g. :class:`PgVectorStore`) should raise
                        :class:`ValueError` if this argument is absent.

        Raises:
            ValueError: If *embeddings* is required but not provided, or if
                        ``len(docs) != len(embeddings)``.
        """
        ...

    @abstractmethod
    def search(
        self,
        query_embedding: List[float],
        top_k: int = 10,
        filter: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[Document, float]]:
        """Perform approximate nearest-neighbour (ANN) vector search.

        Args:
            query_embedding: Dense query vector.
            top_k:           Maximum number of results to return.
            filter:          Optional metadata filter.  Key semantics are
                             store-specific — see concrete implementations.

        Returns:
            List of ``(Document, score)`` tuples, sorted by **descending**
            similarity score.
        """
        ...
