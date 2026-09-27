"""Registry that maps file-extension strings to loader instances."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Type

from .html_loader import HTMLLoader
from .pdf_loader import PDFLoader

logger = logging.getLogger(__name__)


class LoaderRegistry:
    """Maps file extensions to their loader classes.

    Built-in loaders are registered at construction time.  Custom loaders can
    be added at runtime via :meth:`register`.

    Usage::

        registry = LoaderRegistry()
        loader = registry.get_loader(".pdf")   # returns a PDFLoader instance
        docs = loader.load("/path/to/doc.pdf")
    """

    def __init__(self) -> None:
        self._registry: Dict[str, Type] = {
            ".pdf": PDFLoader,
            ".html": HTMLLoader,
            ".htm": HTMLLoader,
        }

    # ── Public API ────────────────────────────────────────────────────────

    def register(self, extension: str, loader_class: Type) -> None:
        """Register a loader class for a file extension.

        The extension is normalised to lowercase with a leading dot so that
        ``"PDF"``, ``".PDF"`` and ``".pdf"`` all map to the same slot.

        Args:
            extension:    File extension, with or without a leading dot.
            loader_class: Class that implements a ``load(source)`` method.
        """
        ext = self._normalise(extension)
        self._registry[ext] = loader_class
        logger.debug("LoaderRegistry: registered %s -> %s", ext, loader_class.__name__)

    def get_loader(self, extension: str) -> Any:
        """Return an instantiated loader for *extension*.

        Args:
            extension: File extension (e.g. ``".pdf"`` or ``"html"``).

        Returns:
            A fresh loader instance.

        Raises:
            ValueError: When no loader is registered for the extension.
        """
        ext = self._normalise(extension)
        if ext not in self._registry:
            available = sorted(self._registry)
            raise ValueError(
                f"No loader registered for extension {ext!r}.  "
                f"Available extensions: {available}"
            )
        return self._registry[ext]()

    def supported_extensions(self) -> List[str]:
        """Return a sorted list of all registered extensions."""
        return sorted(self._registry.keys())

    def supports(self, extension: str) -> bool:
        """Return ``True`` if a loader exists for *extension*."""
        return self._normalise(extension) in self._registry

    # ── Private helpers ───────────────────────────────────────────────────

    @staticmethod
    def _normalise(extension: str) -> str:
        ext = extension.strip().lower()
        if not ext.startswith("."):
            ext = "." + ext
        return ext
