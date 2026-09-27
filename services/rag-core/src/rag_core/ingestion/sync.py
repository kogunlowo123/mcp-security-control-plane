"""DocumentSync — S3-to-vector-store ingestion pipeline."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import boto3
import psycopg2
from langchain_core.documents import Document
from psycopg2.extras import execute_values

from ..chunking.recursive import RecursiveChunker
from ..config.settings import Settings
from ..embeddings.local_bge import LocalBGEEmbedder
from ..enrichment.acl_stamper import ACLStamper
from ..enrichment.metadata import MetadataEnricher
from ..enrichment.pii_tagger import PIITagger
from ..ingestion.loader_registry import LoaderRegistry
from ..stores.opensearch_store import OpenSearchStore
from ..stores.pgvector_store import PgVectorStore

logger = logging.getLogger(__name__)

_SYNC_STATE_TABLE = "rag_sync_state"


class DocumentSync:
    """Scans an S3 bucket for new/updated documents and syncs them to the
    pgvector and OpenSearch vector stores.

    Change detection is etag-based: an object is only re-processed when its
    S3 ETag differs from the value recorded in the ``rag_sync_state``
    PostgreSQL table.

    Usage::

        sync = DocumentSync(settings)
        result = sync.run()
        print(result)  # {"total": 42, "synced": 3, "skipped": 39, "failed": 0}
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.s3 = boto3.client("s3", region_name=settings.BEDROCK_REGION)
        self.loader_registry = LoaderRegistry()
        self.chunker = RecursiveChunker(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
        )
        self.embedder = LocalBGEEmbedder(model_name=settings.EMBEDDING_MODEL)
        self.pgvector = PgVectorStore(settings.POSTGRES_URL, dim=settings.EMBEDDING_DIM)
        self.opensearch = OpenSearchStore(settings.OPENSEARCH_URL, dim=settings.EMBEDDING_DIM)
        self.metadata_enricher = MetadataEnricher()
        self.pii_tagger = PIITagger()
        self.acl_stamper = ACLStamper()
        self._pg_conn: Optional[psycopg2.extensions.connection] = None

    # ── PostgreSQL helpers ────────────────────────────────────────────────

    def _get_pg_conn(self) -> psycopg2.extensions.connection:
        if self._pg_conn is None or self._pg_conn.closed:
            self._pg_conn = psycopg2.connect(self.settings.POSTGRES_URL)
        return self._pg_conn

    def _ensure_schema(self) -> None:
        conn = self._get_pg_conn()
        with conn.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {_SYNC_STATE_TABLE} (
                    s3_key          TEXT        PRIMARY KEY,
                    etag            TEXT        NOT NULL,
                    last_synced_at  TIMESTAMPTZ NOT NULL,
                    doc_count       INTEGER     NOT NULL DEFAULT 0,
                    status          TEXT        NOT NULL DEFAULT 'ok',
                    error_msg       TEXT
                )
            """)
        conn.commit()

    def _get_synced_etags(self) -> Dict[str, str]:
        conn = self._get_pg_conn()
        with conn.cursor() as cur:
            cur.execute(f"SELECT s3_key, etag FROM {_SYNC_STATE_TABLE}")
            return {row[0]: row[1] for row in cur.fetchall()}

    def _upsert_sync_state(
        self,
        s3_key: str,
        etag: str,
        doc_count: int,
        status: str = "ok",
        error_msg: Optional[str] = None,
    ) -> None:
        conn = self._get_pg_conn()
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {_SYNC_STATE_TABLE}
                    (s3_key, etag, last_synced_at, doc_count, status, error_msg)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (s3_key) DO UPDATE
                    SET etag           = EXCLUDED.etag,
                        last_synced_at = EXCLUDED.last_synced_at,
                        doc_count      = EXCLUDED.doc_count,
                        status         = EXCLUDED.status,
                        error_msg      = EXCLUDED.error_msg
                """,
                (s3_key, etag, datetime.now(timezone.utc), doc_count, status, error_msg),
            )
        conn.commit()

    # ── S3 helpers ────────────────────────────────────────────────────────

    def _list_s3_objects(self) -> List[Dict[str, str]]:
        """Paginate through all objects in the configured S3 bucket."""
        objects: List[Dict[str, str]] = []
        paginator = self.s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.settings.S3_BUCKET):
            for obj in page.get("Contents", []):
                objects.append(
                    {"key": obj["Key"], "etag": obj["ETag"].strip('"')}
                )
        return objects

    def _download_object(self, key: str) -> bytes:
        response = self.s3.get_object(Bucket=self.settings.S3_BUCKET, Key=key)
        return response["Body"].read()

    # ── Processing pipeline ───────────────────────────────────────────────

    def _process_object(
        self, key: str, raw_bytes: bytes
    ) -> List[Tuple[Document, List[float]]]:
        """Run a single S3 object through the full ingestion pipeline.

        Returns a list of ``(Document, embedding)`` pairs ready for storage.
        """
        ext = Path(key).suffix.lower()
        if not self.loader_registry.supports(ext):
            logger.warning("Unsupported extension %r — skipping %s", ext, key)
            return []

        loader = self.loader_registry.get_loader(ext)
        raw_docs = loader.load(raw_bytes)
        if not raw_docs:
            logger.info("No content extracted from %s", key)
            return []

        # Enrich every page-level document
        enriched_docs: List[Document] = []
        for doc in raw_docs:
            doc = self.metadata_enricher.enrich(doc, source=key)
            doc = self.pii_tagger.tag(doc)
            doc = self.acl_stamper.stamp(doc)
            enriched_docs.append(doc)

        # Chunk into retrieval-sized pieces
        chunks: List[Document] = []
        for doc in enriched_docs:
            chunks.extend(self.chunker.chunk(doc.page_content, doc.metadata))

        if not chunks:
            return []

        # Embed all chunks in one batch call
        texts = [c.page_content for c in chunks]
        embeddings = self.embedder.embed(texts)

        return list(zip(chunks, embeddings))

    # ── Public API ────────────────────────────────────────────────────────

    def run(self, full_resync: bool = False) -> Dict[str, int]:
        """Execute one sync cycle.

        Args:
            full_resync: Re-process every object regardless of cached ETags.

        Returns:
            Summary dict ``{"total": N, "synced": N, "skipped": N, "failed": N}``.
        """
        if not self.settings.S3_BUCKET:
            logger.warning("S3_BUCKET is not configured — sync aborted.")
            return {"total": 0, "synced": 0, "skipped": 0, "failed": 0}

        self._ensure_schema()
        known_etags: Dict[str, str] = {} if full_resync else self._get_synced_etags()

        s3_objects = self._list_s3_objects()
        stats: Dict[str, int] = {
            "total": len(s3_objects),
            "synced": 0,
            "skipped": 0,
            "failed": 0,
        }

        for obj in s3_objects:
            key, etag = obj["key"], obj["etag"]

            if known_etags.get(key) == etag:
                stats["skipped"] += 1
                continue

            logger.info("Syncing %s (etag=%s)", key, etag)
            try:
                raw_bytes = self._download_object(key)
                pairs = self._process_object(key, raw_bytes)

                if pairs:
                    docs, embeddings = zip(*pairs)
                    doc_list = list(docs)
                    emb_list = list(embeddings)
                    self.pgvector.upsert(doc_list, emb_list)
                    self.opensearch.upsert(doc_list, emb_list)

                self._upsert_sync_state(key, etag, len(pairs))
                stats["synced"] += 1

            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed to sync %s: %s", key, exc)
                self._upsert_sync_state(
                    key, etag, 0, status="error", error_msg=str(exc)
                )
                stats["failed"] += 1

        logger.info("DocumentSync complete: %s", stats)
        return stats

    def close(self) -> None:
        """Release the PostgreSQL connection."""
        if self._pg_conn and not self._pg_conn.closed:
            self._pg_conn.close()

    def __enter__(self) -> "DocumentSync":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
