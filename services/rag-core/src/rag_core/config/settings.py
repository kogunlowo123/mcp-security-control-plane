"""Application settings loaded from environment variables or a .env file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the RAG core service.

    All values can be set via environment variables (case-insensitive) or a
    .env file in the working directory.  Required fields (no default) must be
    supplied — the process will raise a validation error at startup otherwise.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Storage ───────────────────────────────────────────────────────────
    POSTGRES_URL: str
    """Full PostgreSQL DSN, e.g. postgresql://user:pass@host:5432/dbname"""

    OPENSEARCH_URL: str
    """OpenSearch endpoint, e.g. https://localhost:9200"""

    # ── AWS / Bedrock ─────────────────────────────────────────────────────
    BEDROCK_REGION: str = "us-east-1"
    """AWS region for Bedrock API calls."""

    # ── Embedding ─────────────────────────────────────────────────────────
    EMBEDDING_MODEL: str = "BAAI/bge-large-en-v1.5"
    """HuggingFace model ID used by LocalBGEEmbedder."""

    EMBEDDING_DIM: int = 1536
    """Dimensionality of the embedding vectors.

    bge-large-en-v1.5 outputs 1024 dims; titan-embed-text-v2 outputs 1024 by
    default (configurable to 256/512/1024).  Set to 1024 when using either
    model without padding.  The default of 1536 matches OpenAI ada-002 for
    compatibility with existing pgvector schemas.
    """

    # ── Chunking ──────────────────────────────────────────────────────────
    CHUNK_SIZE: int = 512
    """Target character length for each text chunk."""

    CHUNK_OVERLAP: int = 64
    """Number of characters shared between adjacent chunks."""

    # ── Retrieval ─────────────────────────────────────────────────────────
    TOP_K: int = 10
    """Number of results returned by the retriever before reranking."""

    RERANK_TOP_K: int = 5
    """Number of results kept after cross-encoder reranking."""

    # ── S3 ────────────────────────────────────────────────────────────────
    S3_BUCKET: str = ""
    """S3 bucket name for document ingestion.  Leave empty to disable S3 sync."""

    # ── Cache ─────────────────────────────────────────────────────────────
    REDIS_URL: str = ""
    """Optional Redis URL for embedding cache.  Empty disables Redis caching."""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached application settings singleton."""
    return Settings()
