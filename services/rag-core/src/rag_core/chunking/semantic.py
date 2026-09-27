"""Semantic chunker — splits text on topic-shift boundaries detected via
sentence embeddings."""

from __future__ import annotations

import re
from typing import List, Optional

import numpy as np
from langchain_core.documents import Document

from .base import BaseChunker


class SemanticChunker(BaseChunker):
    """Chunks text by detecting semantic boundaries between adjacent sentences.

    The algorithm:

    1. Split *text* into sentences using punctuation rules.
    2. Embed all sentences with a local sentence-transformer model.
    3. Compute cosine similarity between each consecutive sentence pair.
    4. Start a new chunk wherever similarity drops below *similarity_threshold*
       or the current chunk would exceed *max_chunk_size* characters.
    5. Merge tiny trailing chunks (< *min_chunk_size* chars) into the previous
       chunk to avoid orphan fragments.

    Args:
        model_name:           HuggingFace model for sentence embeddings.
        similarity_threshold: Cosine similarity below which a topic shift is
                              detected (range 0–1, default 0.75).
        max_chunk_size:       Hard character cap per chunk (default 512).
        min_chunk_size:       Chunks smaller than this are merged upward
                              (default 64).
    """

    _SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

    def __init__(
        self,
        model_name: str = "BAAI/bge-large-en-v1.5",
        similarity_threshold: float = 0.75,
        max_chunk_size: int = 512,
        min_chunk_size: int = 64,
    ) -> None:
        self.model_name = model_name
        self.similarity_threshold = similarity_threshold
        self.max_chunk_size = max_chunk_size
        self.min_chunk_size = min_chunk_size
        self._model = None

    # ── Private helpers ───────────────────────────────────────────────────

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        return self._model

    def _split_sentences(self, text: str) -> List[str]:
        raw = self._SENTENCE_SPLIT.split(text.strip())
        return [s.strip() for s in raw if s.strip()]

    @staticmethod
    def _cosine(a: np.ndarray, b: np.ndarray) -> float:
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na == 0.0 or nb == 0.0:
            return 0.0
        return float(np.dot(a, b) / (na * nb))

    # ── BaseChunker interface ────────────────────────────────────────────

    def chunk(self, text: str, metadata: dict) -> List[Document]:
        if not text or not text.strip():
            return []

        sentences = self._split_sentences(text)
        if not sentences:
            return []
        if len(sentences) == 1:
            meta = dict(metadata)
            meta.update(chunk_index=0, chunk_count=1, chunker="semantic")
            return [Document(page_content=sentences[0], metadata=meta)]

        model = self._get_model()
        embeddings: np.ndarray = model.encode(
            sentences, convert_to_numpy=True, show_progress_bar=False
        )

        # Build groups of semantically cohesive sentences
        groups: List[List[str]] = []
        current: List[str] = [sentences[0]]

        for i in range(1, len(sentences)):
            sim = self._cosine(embeddings[i - 1], embeddings[i])
            current_len = sum(len(s) for s in current)

            if sim < self.similarity_threshold or current_len >= self.max_chunk_size:
                groups.append(current)
                current = [sentences[i]]
            else:
                current.append(sentences[i])

        if current:
            groups.append(current)

        # Merge undersized groups into the previous one
        merged: List[List[str]] = []
        for group in groups:
            group_len = sum(len(s) for s in group)
            if merged and group_len < self.min_chunk_size:
                merged[-1].extend(group)
            else:
                merged.append(group)

        # Build Document objects
        total = len(merged)
        documents: List[Document] = []
        for idx, group in enumerate(merged):
            chunk_text = " ".join(group).strip()
            if not chunk_text:
                continue
            meta = dict(metadata)
            meta.update(chunk_index=idx, chunk_count=total, chunker="semantic")
            documents.append(Document(page_content=chunk_text, metadata=meta))

        # Fix count if we skipped any empty chunks
        actual_total = len(documents)
        if actual_total != total:
            for doc in documents:
                doc.metadata["chunk_count"] = actual_total

        return documents
