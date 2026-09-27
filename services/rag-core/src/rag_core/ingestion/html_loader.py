"""HTML document loader using BeautifulSoup."""

import logging
from pathlib import Path
from typing import List, Union

from langchain_core.documents import Document

logger = logging.getLogger(__name__)

# Tags whose content we always discard
_NOISE_TAGS = ["script", "style", "nav", "footer", "header", "noscript", "svg", "iframe"]


class HTMLLoader:
    """Loads HTML files or raw HTML strings and returns :class:`Document` objects.

    Extracts visible text while stripping boilerplate (scripts, styles, nav,
    footers).  Prefers ``<article>`` / ``<main>`` / ``<section>`` blocks when
    present; falls back to full-page text extraction.

    Example::

        loader = HTMLLoader()
        docs = loader.load("/path/to/policy.html")
        print(docs[0].metadata["title"])
    """

    def load(
        self,
        source: Union[str, Path, bytes],
        source_name: str = "",
    ) -> List[Document]:
        """Load HTML content from a file path, bytes, or inline string.

        Args:
            source:      File path (``str`` or :class:`~pathlib.Path`), raw
                         HTML bytes, or a raw HTML string.
            source_name: Optional label to use as ``metadata["source"]``; only
                         used when *source* is bytes or inline HTML.

        Returns:
            A list containing a single :class:`Document` with the extracted
            visible text, or an empty list when no text is found.

        Raises:
            ImportError: If ``beautifulsoup4`` is not installed.
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise ImportError(
                "beautifulsoup4 is required.  Install it with: pip install beautifulsoup4"
            ) from exc

        if isinstance(source, bytes):
            raw_html = source.decode("utf-8", errors="replace")
            label = source_name or "<bytes>"
        elif isinstance(source, Path) or (isinstance(source, str) and Path(source).exists()):
            path = Path(source)
            raw_html = path.read_text(encoding="utf-8", errors="replace")
            label = source_name or str(path)
        else:
            # Treat as inline HTML string
            raw_html = str(source)
            label = source_name or "<inline>"

        soup = BeautifulSoup(raw_html, "html.parser")

        # Remove boilerplate elements
        for tag in soup(_NOISE_TAGS):
            tag.decompose()

        # Capture page title
        title_tag = soup.find("title")
        page_title = title_tag.get_text(strip=True) if title_tag else ""

        # Prefer semantic content blocks
        content_blocks = soup.find_all(["article", "main", "section"])
        if content_blocks:
            sections = []
            for block in content_blocks:
                text = block.get_text(separator="\n", strip=True)
                if text:
                    sections.append(text)
            full_text = "\n\n".join(sections)
        else:
            full_text = soup.get_text(separator="\n", strip=True)

        # Collapse excessive blank lines
        lines = [line.strip() for line in full_text.splitlines()]
        lines = [line for line in lines if line]
        full_text = "\n".join(lines)

        if not full_text:
            logger.debug("No visible text extracted from HTML: %s", label)
            return []

        metadata: dict = {
            "source": label,
            "title": page_title,
            "doc_type": "html",
        }

        logger.info("HTMLLoader: extracted %d chars from %s", len(full_text), label)
        return [Document(page_content=full_text, metadata=metadata)]
