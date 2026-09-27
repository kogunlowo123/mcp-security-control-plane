"""Structural chunker — respects Markdown headings and document sections."""

from __future__ import annotations

import re
from typing import List

from langchain_core.documents import Document

from .base import BaseChunker

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_BLANK_LINES_RE = re.compile(r"\n{3,}")


class StructuralChunker(BaseChunker):
    """Chunks text by honouring document structure (Markdown headings).

    Splits on ``# Heading`` boundaries.  When no Markdown headings are found
    it falls back to splitting on runs of 3+ blank lines.  Chunks that exceed
    *max_chunk_size* characters are further split without losing the heading
    context.

    Args:
        max_chunk_size:    Hard character cap per output chunk (default 2048).
        include_headings:  Prepend the section heading to each chunk text so
                           that the heading context is preserved (default True).
    """

    def __init__(
        self,
        max_chunk_size: int = 2048,
        include_headings: bool = True,
    ) -> None:
        self.max_chunk_size = max_chunk_size
        self.include_headings = include_headings

    # ── Private helpers ───────────────────────────────────────────────────

    def _split_by_headings(self, text: str) -> List[dict]:
        """Return ``[{heading, level, content}]`` dicts for each section."""
        sections: List[dict] = []
        last_end = 0
        current_heading = ""
        current_level = 0

        for m in _HEADING_RE.finditer(text):
            body = text[last_end : m.start()].strip()
            if body or current_heading:
                sections.append(
                    {"heading": current_heading, "level": current_level, "content": body}
                )
            current_heading = m.group(2).strip()
            current_level = len(m.group(1))
            last_end = m.end()

        # Final section after the last heading
        remaining = text[last_end:].strip()
        if remaining or current_heading:
            sections.append(
                {"heading": current_heading, "level": current_level, "content": remaining}
            )

        return sections

    def _hard_split(self, text: str) -> List[str]:
        """Split a long piece of text without discarding any characters."""
        # First try splitting on paragraph breaks
        parts = [p.strip() for p in _BLANK_LINES_RE.split(text) if p.strip()]
        if not parts:
            parts = [text]

        result: List[str] = []
        for part in parts:
            if len(part) <= self.max_chunk_size:
                result.append(part)
            else:
                # Hard character split as a last resort
                for i in range(0, len(part), self.max_chunk_size):
                    sub = part[i : i + self.max_chunk_size].strip()
                    if sub:
                        result.append(sub)
        return result

    # ── BaseChunker interface ────────────────────────────────────────────

    def chunk(self, text: str, metadata: dict) -> List[Document]:
        if not text or not text.strip():
            return []

        sections = self._split_by_headings(text)

        # Fallback: no headings found — split by blank lines
        if not any(s["heading"] for s in sections):
            parts = [p.strip() for p in _BLANK_LINES_RE.split(text.strip()) if p.strip()]
            if not parts:
                parts = [text.strip()]
            sections = [{"heading": "", "level": 0, "content": p} for p in parts]

        documents: List[Document] = []
        chunk_index = 0

        for section in sections:
            heading: str = section["heading"]
            content: str = section["content"]

            if self.include_headings and heading:
                chunk_text = f"{heading}\n\n{content}" if content else heading
            else:
                chunk_text = content or heading

            chunk_text = chunk_text.strip()
            if not chunk_text:
                continue

            sub_chunks = (
                self._hard_split(chunk_text)
                if len(chunk_text) > self.max_chunk_size
                else [chunk_text]
            )

            for sub in sub_chunks:
                if not sub:
                    continue
                meta = dict(metadata)
                meta["chunk_index"] = chunk_index
                meta["heading"] = heading
                meta["heading_level"] = section["level"]
                meta["chunker"] = "structural"
                documents.append(Document(page_content=sub, metadata=meta))
                chunk_index += 1

        total = len(documents)
        for doc in documents:
            doc.metadata["chunk_count"] = total

        return documents
