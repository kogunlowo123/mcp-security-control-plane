"""PDF document loader using pypdf."""

import io
import logging
from pathlib import Path
from typing import List, Union

from langchain_core.documents import Document

logger = logging.getLogger(__name__)


class PDFLoader:
    """Loads PDF files and returns one :class:`Document` per page.

    Uses ``pypdf`` for extraction.  Empty pages are silently skipped.

    Example::

        loader = PDFLoader()
        docs = loader.load("/path/to/policy.pdf")
        for doc in docs:
            print(doc.metadata["page"], doc.page_content[:80])
    """

    def load(self, source: Union[str, Path, bytes]) -> List[Document]:
        """Load a PDF from a file path or raw bytes.

        Args:
            source: File path (``str`` or :class:`~pathlib.Path`) **or** raw
                    PDF bytes.

        Returns:
            Ordered list of :class:`Document` objects, one per non-empty page.

        Raises:
            ImportError: If ``pypdf`` is not installed.
            FileNotFoundError: If *source* is a path that does not exist.
        """
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ImportError(
                "pypdf is required for PDF loading.  Install it with: pip install pypdf"
            ) from exc

        if isinstance(source, bytes):
            reader = PdfReader(io.BytesIO(source))
            source_label = "<bytes>"
        else:
            path = Path(source)
            if not path.exists():
                raise FileNotFoundError(f"PDF file not found: {path}")
            reader = PdfReader(str(path))
            source_label = str(path)

        num_pages = len(reader.pages)
        documents: List[Document] = []

        for page_num, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            text = text.strip()

            if not text:
                logger.debug("Skipping empty page %d/%d in %s", page_num + 1, num_pages, source_label)
                continue

            metadata: dict = {
                "source": source_label,
                "page": page_num + 1,
                "total_pages": num_pages,
                "doc_type": "pdf",
            }

            # Preserve any annotations / labels pypdf can surface
            if hasattr(page, "annotations") and page.annotations:
                metadata["has_annotations"] = True

            documents.append(Document(page_content=text, metadata=metadata))

        logger.info("PDFLoader: extracted %d pages from %s", len(documents), source_label)
        return documents
