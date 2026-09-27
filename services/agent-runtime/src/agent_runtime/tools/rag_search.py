"""RAGSearchTool — hybrid retrieval over the MCP security policy corpus.

Available to T1+ agents only. Calls the rag-core service's hybrid retriever
(dense vector + BM25 sparse) and returns ranked documents with citations.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import structlog

from agent_runtime.tools.base import MCPTool

logger = structlog.get_logger(__name__)

_RAG_CORE_BASE_URL = os.environ.get("RAG_CORE_URL", "http://rag-core:8080")
_RAG_CORE_API_KEY = os.environ.get("RAG_CORE_API_KEY", "")
_DEFAULT_TOP_K = 5
_DEFAULT_MIN_SCORE = 0.0
_HTTP_TIMEOUT = 15.0


class RAGSearchTool(MCPTool):
    """Hybrid RAG retrieval over the MCP security policy corpus.

    Sends the agent's query to the rag-core service which runs a combined
    dense (FAISS / pgvector) + sparse (BM25) retrieval and returns the
    top-K ranked chunks with source metadata.

    Only available to T1 and above; instantiation with a T0 caller will
    raise :class:`PermissionError` via the base class.
    """

    tool_id = "rag_search"
    display_name = "RAG Policy Search"
    description = (
        "Performs hybrid vector+BM25 retrieval over the MCP security policy "
        "corpus. Returns ranked document chunks with source citations."
    )
    min_tier = "T1"
    read_only = True
    input_schema = {
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {"type": "string", "maxLength": 2048},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            "min_score": {"type": "number", "minimum": 0.0, "maximum": 1.0, "default": 0.0},
            "filter_tags": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
    }

    async def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a hybrid RAG search against the policy corpus.

        Args:
            params: Must include ``query`` (str). Optional: ``top_k`` (int),
                ``min_score`` (float), ``filter_tags`` (list[str]).

        Returns:
            ``{"success": True, "data": {"documents": [...], "query": ...,
            "total_retrieved": N}}``.
            Each document element::

                {
                    "id": str,
                    "content": str,
                    "score": float,
                    "source": str,       # document filename / URL
                    "section": str,      # heading or chunk label
                    "metadata": dict,
                    "citation": str,     # formatted citation string
                }
        """
        query: str = params["query"]
        top_k: int = int(params.get("top_k", _DEFAULT_TOP_K))
        min_score: float = float(params.get("min_score", _DEFAULT_MIN_SCORE))
        filter_tags: list[str] = params.get("filter_tags", [])

        log = logger.bind(
            tool=self.tool_id,
            caller=self._caller_agent_id,
            query_len=len(query),
            top_k=top_k,
        )
        log.info("rag_search.execute")

        request_body: dict[str, Any] = {
            "query": query,
            "top_k": top_k,
            "min_score": min_score,
        }
        if filter_tags:
            request_body["filter_tags"] = filter_tags

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                response = await client.post(
                    f"{_RAG_CORE_BASE_URL}/api/v1/retrieve",
                    json=request_body,
                    headers={
                        "X-API-Key": _RAG_CORE_API_KEY,
                        "X-Caller-Agent": self._caller_agent_id,
                        "X-Caller-Tier": self._caller_tier,
                    },
                )
                response.raise_for_status()

        except httpx.HTTPStatusError as exc:
            log.error(
                "rag_search.http_error",
                status_code=exc.response.status_code,
                detail=exc.response.text[:500],
            )
            return self._err(
                f"RAG service returned HTTP {exc.response.status_code}: {exc.response.text[:200]}",
                code="RAG_HTTP_ERROR",
            )
        except httpx.RequestError as exc:
            log.error("rag_search.request_error", error=str(exc))
            return self._err(f"RAG service unreachable: {exc}", code="RAG_UNREACHABLE")

        raw: dict[str, Any] = response.json()
        documents: list[dict[str, Any]] = raw.get("documents", [])

        # Normalise and add citation strings
        normalised: list[dict[str, Any]] = []
        for doc in documents:
            doc_id = doc.get("id", "unknown")
            source = doc.get("source", "unknown")
            section = doc.get("section", "")
            score = doc.get("score", 0.0)
            citation = f"[{source}]"
            if section:
                citation += f" § {section}"
            normalised.append(
                {
                    "id": doc_id,
                    "content": doc.get("content", ""),
                    "score": score,
                    "source": source,
                    "section": section,
                    "metadata": doc.get("metadata", {}),
                    "citation": citation,
                }
            )

        log.info("rag_search.complete", docs_returned=len(normalised))
        return self._ok(
            data={"documents": normalised, "query": query, "total_retrieved": len(normalised)},
            metadata={"rag_core_request_id": raw.get("request_id")},
        )
