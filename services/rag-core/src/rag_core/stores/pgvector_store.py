"""PostgreSQL / pgvector vector store implementation."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from langchain_core.documents import Document
from psycopg2.extras import execute_values

from .vector_base import VectorStore

logger = logging.getLogger(__name__)

_CREATE_EXTENSION = "CREATE EXTENSION IF NOT EXISTS vector"

_CREATE_TABLE_TMPL = """
CREATE TABLE IF NOT EXISTS {table} (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    content     TEXT        NOT NULL,
    metadata    JSONB       NOT NULL DEFAULT '{{}}'::jsonb,
    embedding   vector({dim}) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

_CREATE_INDEX_TMPL = """
CREATE INDEX IF NOT EXISTS {table}_embedding_idx
    ON {table} USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100)
"""


class PgVectorStore(VectorStore):
    """Vector store backed by PostgreSQL with the pgvector extension.

    Documents are persisted in a ``documents`` table (or a custom name) with
    an ``embedding vector(dim)`` column.  Cosine-distance ANN search is
    performed via pgvector's ``<=>`` operator with an IVFFlat index.

    Args:
        postgres_url: Full DSN string, e.g.
                      ``postgresql://user:pass@host:5432/dbname``.
        dim:          Vector dimensionality — must match the embedding model
                      output (default 1536 for compatibility; bge-large uses
                      1024, Titan v2 uses 1024 by default).
        table:        Table name for documents (default ``"documents"``).
    """

    def __init__(
        self,
        postgres_url: str,
        dim: int = 1536,
        table: str = "documents",
    ) -> None:
        self.postgres_url = postgres_url
        self.dim = dim
        self.table = table
        self._conn: Optional[psycopg2.extensions.connection] = None
        self._ensure_schema()

    # ── Connection ────────────────────────────────────────────────────────

    def _get_conn(self) -> psycopg2.extensions.connection:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.postgres_url)
            self._conn.autocommit = False
        return self._conn

    def _ensure_schema(self) -> None:
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(_CREATE_EXTENSION)
            cur.execute(_CREATE_TABLE_TMPL.format(table=self.table, dim=self.dim))
            try:
                cur.execute(_CREATE_INDEX_TMPL.format(table=self.table))
            except psycopg2.errors.FeatureNotSupported:
                # IVFFlat index requires at least one row; ignore on empty table
                conn.rollback()
                logger.debug(
                    "IVFFlat index creation deferred (table %s is empty).", self.table
                )
                return
            except psycopg2.errors.UndefinedObject:
                conn.rollback()
                return
        conn.commit()

    # ── VectorStore interface ────────────────────────────────────────────

    def upsert(
        self,
        docs: List[Document],
        embeddings: Optional[List[List[float]]] = None,
    ) -> None:
        """Upsert documents with their pre-computed embeddings.

        Raises:
            ValueError: If *embeddings* is None or lengths mismatch.
        """
        if not docs:
            return
        if embeddings is None:
            raise ValueError(
                "PgVectorStore.upsert requires pre-computed embeddings; "
                "call your embedder first."
            )
        if len(docs) != len(embeddings):
            raise ValueError(
                f"len(docs)={len(docs)} != len(embeddings)={len(embeddings)}"
            )

        conn = self._get_conn()
        rows = []
        for doc, emb in zip(docs, embeddings):
            doc_id = doc.metadata.get("id") or str(uuid.uuid4())
            vec_str = "[" + ",".join(str(v) for v in emb) + "]"
            rows.append(
                (doc_id, doc.page_content, json.dumps(doc.metadata), vec_str)
            )

        with conn.cursor() as cur:
            execute_values(
                cur,
                f"""
                INSERT INTO {self.table} (id, content, metadata, embedding)
                VALUES %s
                ON CONFLICT (id) DO UPDATE
                    SET content    = EXCLUDED.content,
                        metadata   = EXCLUDED.metadata,
                        embedding  = EXCLUDED.embedding,
                        created_at = NOW()
                """,
                rows,
                template="(%s::uuid, %s, %s::jsonb, %s::vector)",
            )
        conn.commit()
        logger.debug("PgVectorStore: upserted %d documents.", len(docs))

    def search(
        self,
        query_embedding: List[float],
        top_k: int = 10,
        filter: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[Document, float]]:
        """Cosine-distance ANN search.

        Supported filter keys:

        * ``"acl_tiers"`` (``str | List[str]``) — the document's
          ``metadata->>'acl_tiers'`` array must overlap with the supplied
          tier(s).
        * Any other key is matched as ``metadata->>'key' = value``.
        """
        conn = self._get_conn()
        vec_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

        where_clauses: List[str] = []
        params: List[Any] = []

        if filter:
            for key, value in filter.items():
                if key == "acl_tiers":
                    tier_list = value if isinstance(value, list) else [value]
                    where_clauses.append(
                        "EXISTS ("
                        "  SELECT 1 FROM jsonb_array_elements_text(metadata->'acl_tiers') AS t"
                        "  WHERE t = ANY(%s::text[])"
                        ")"
                    )
                    params.append(tier_list)
                else:
                    where_clauses.append(f"metadata->>{key!r} = %s")
                    params.append(str(value))

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        sql = f"""
            SELECT content,
                   metadata,
                   1 - (embedding <=> %s::vector) AS score
            FROM   {self.table}
            {where_sql}
            ORDER  BY embedding <=> %s::vector
            LIMIT  %s
        """

        all_params = [vec_str] + params + [vec_str, top_k]

        with conn.cursor() as cur:
            cur.execute(sql, all_params)
            rows = cur.fetchall()

        results: List[Tuple[Document, float]] = []
        for content, metadata, score in rows:
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            results.append((Document(page_content=content, metadata=metadata), float(score)))

        return results

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def close(self) -> None:
        """Release the PostgreSQL connection."""
        if self._conn and not self._conn.closed:
            self._conn.close()

    def __enter__(self) -> "PgVectorStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
