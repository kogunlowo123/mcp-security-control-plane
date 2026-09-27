"""Local BAAI/bge-large-en-v1.5 embedder via sentence-transformers."""

from __future__ import annotations

import logging
from typing import List, Optional

from .base import BaseEmbedder

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "BAAI/bge-large-en-v1.5"

# BGE models perform better for retrieval when the query (not the passage)
# carries this instruction prefix.
_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class LocalBGEEmbedder(BaseEmbedder):
    """Embedder using BAAI/bge-large-en-v1.5 loaded via sentence-transformers.

    The model is loaded lazily on first call so that import time is fast.

    BGE-large-en-v1.5 produces **1024-dimensional** normalised vectors.  If
    your pgvector schema was created with ``vector(1536)`` you must either set
    ``EMBEDDING_DIM=1024`` in settings or use a padding wrapper.

    Args:
        model_name:         HuggingFace model identifier.
        device:             Torch device string (e.g. ``"cpu"``, ``"cuda:0"``).
                            When ``None`` sentence-transformers auto-selects.
        batch_size:         Number of texts encoded per forward pass.
        add_query_prefix:   Prepend the BGE query instruction to single-query
                            calls via :meth:`embed_query`.
    """

    def __init__(
        self,
        model_name: str = _DEFAULT_MODEL,
        device: Optional[str] = None,
        batch_size: int = 32,
        add_query_prefix: bool = True,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self.add_query_prefix = add_query_prefix
        self._model = None

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, device=self.device)
            dim = self._model.get_sentence_embedding_dimension()
            logger.info("Loaded %s (dim=%d, device=%s)", self.model_name, dim, self.device)
        return self._model

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of passage texts.

        Raises:
            ValueError: If *texts* is empty.
        """
        if not texts:
            raise ValueError("embed() requires a non-empty list of texts.")

        model = self._get_model()
        vectors = model.encode(
            texts,
            batch_size=self.batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vectors.tolist()

    def embed_query(self, query: str) -> List[float]:
        """Embed a single query string.

        Prepends the BGE query instruction prefix when *add_query_prefix* is
        ``True``, improving retrieval quality as recommended by BAAI.

        Args:
            query: The user query string.

        Returns:
            Single embedding vector as a ``List[float]``.
        """
        prefixed = (_QUERY_PREFIX + query) if self.add_query_prefix else query
        return self.embed([prefixed])[0]
