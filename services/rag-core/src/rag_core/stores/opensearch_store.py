"""OpenSearch vector store — kNN dense search + BM25 sparse search."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from langchain_core.documents import Document
from opensearchpy import OpenSearch, RequestsHttpConnection

from .vector_base import VectorStore

logger = logging.getLogger(__name__)

_INDEX_NAME = "rag_documents"
_DEFAULT_DIM = 1536


def _build_index_mapping(dim: int) -> dict:
    return {
        "settings": {
            "index": {
                "knn": True,
                "knn.algo_param.ef_search": 512,
                "number_of_shards": 2,
                "number_of_replicas": 1,
            }
        },
        "mappings": {
            "properties": {
                "content": {
                    "type": "text",
                    "analyzer": "english",
                },
                "source": {"type": "keyword"},
                "doc_type": {"type": "keyword"},
                "acl_tiers": {"type": "keyword"},
                "metadata": {"type": "object", "enabled": False},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": dim,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "nmslib",
                        "parameters": {"ef_construction": 512, "m": 16},
                    },
                },
            }
        },
    }


class OpenSearchStore(VectorStore):
    """Vector store backed by OpenSearch using both kNN and BM25 retrieval.

    The :meth:`search` method performs **dense kNN** retrieval against the
    ``embedding`` field.  Call :meth:`bm25_search` for sparse BM25 retrieval
    over ``content``.

    Args:
        opensearch_url: OpenSearch endpoint URL.
        index_name:     Index name (default ``"rag_documents"``).
        dim:            Embedding vector dimensionality (default 1536).
    """

    def __init__(
        self,
        opensearch_url: str,
        index_name: str = _INDEX_NAME,
        dim: int = _DEFAULT_DIM,
    ) -> None:
        self.index_name = index_name
        self.dim = dim
        self._client = self._build_client(opensearch_url)
        self._ensure_index()

    # ── Setup ─────────────────────────────────────────────────────────────

    @staticmethod
    def _build_client(url: str) -> OpenSearch:
        parsed = urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 9200
        use_ssl = parsed.scheme == "https"
        http_auth = None
        if parsed.username and parsed.password:
            http_auth = (parsed.username, parsed.password)
        return OpenSearch(
            hosts=[{"host": host, "port": port}],
            http_compress=True,
            use_ssl=use_ssl,
            verify_certs=False,
            http_auth=http_auth,
            connection_class=RequestsHttpConnection,
        )

    def _ensure_index(self) -> None:
        if not self._client.indices.exists(index=self.index_name):
            mapping = _build_index_mapping(self.dim)
            self._client.indices.create(index=self.index_name, body=mapping)
            logger.info("OpenSearchStore: created index %s (dim=%d).", self.index_name, self.dim)

    # ── VectorStore interface ────────────────────────────────────────────

    def upsert(
        self,
        docs: List[Document],
        embeddings: Optional[List[List[float]]] = None,
    ) -> None:
        """Bulk-index documents.  Embeddings are optional but recommended for
        kNN search.
        """
        if not docs:
            return

        bulk_body: List[Any] = []
        for i, doc in enumerate(docs):
            doc_id = doc.metadata.get("id") or str(uuid.uuid4())
            body: Dict[str, Any] = {
                "content": doc.page_content,
                "source": doc.metadata.get("source", ""),
                "doc_type": doc.metadata.get("doc_type", ""),
                "acl_tiers": doc.metadata.get("acl_tiers", []),
                "metadata": doc.metadata,
            }
            if embeddings is not None and i < len(embeddings):
                body["embedding"] = embeddings[i]

            bulk_body.append({"index": {"_index": self.index_name, "_id": doc_id}})
            bulk_body.append(body)

        response = self._client.bulk(body=bulk_body)
        if response.get("errors"):
            logger.warning("OpenSearch bulk upsert had errors: %s", response)
        else:
            logger.debug("OpenSearchStore: indexed %d documents.", len(docs))

    def search(
        self,
        query_embedding: List[float],
        top_k: int = 10,
        filter: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[Document, float]]:
        """Dense kNN search using the ``embedding`` vector field."""
        knn_clause: Dict[str, Any] = {
            "knn": {
                "embedding": {
                    "vector": query_embedding,
                    "k": top_k,
                }
            }
        }

        query = self._apply_acl_filter(knn_clause, filter)
        response = self._client.search(
            index=self.index_name,
            body={"size": top_k, "query": query},
        )
        return self._parse_hits(response)

    # ── Extra: sparse BM25 ────────────────────────────────────────────────

    def bm25_search(
        self,
        query_text: str,
        top_k: int = 10,
        filter: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[Document, float]]:
        """Sparse BM25 full-text search over the ``content`` field.

        This is the *secondary* retrieval path used by :class:`HybridRetriever`
        alongside dense pgvector search.
        """
        match_clause: Dict[str, Any] = {
            "match": {
                "content": {
                    "query": query_text,
                    "operator": "or",
                }
            }
        }

        query = self._apply_acl_filter(match_clause, filter)
        response = self._client.search(
            index=self.index_name,
            body={"size": top_k, "query": query},
        )
        return self._parse_hits(response)

    # ── Private helpers ───────────────────────────────────────────────────

    @staticmethod
    def _apply_acl_filter(
        base_clause: Dict[str, Any],
        filter: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not filter:
            return base_clause
        acl_tiers = filter.get("acl_tiers")
        if not acl_tiers:
            return base_clause
        tier_list = acl_tiers if isinstance(acl_tiers, list) else [acl_tiers]
        return {
            "bool": {
                "must": [base_clause],
                "filter": [{"terms": {"acl_tiers": tier_list}}],
            }
        }

    @staticmethod
    def _parse_hits(response: dict) -> List[Tuple[Document, float]]:
        results: List[Tuple[Document, float]] = []
        for hit in response["hits"]["hits"]:
            src = hit["_source"]
            content = src.get("content", "")
            metadata: dict = src.get("metadata", {})
            metadata["id"] = hit["_id"]
            score = float(hit.get("_score") or 0.0)
            results.append((Document(page_content=content, metadata=metadata), score))
        return results
