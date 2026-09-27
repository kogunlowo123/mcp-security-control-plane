"""Abstract base class for all embedding backends."""

from abc import ABC, abstractmethod
from typing import List


class BaseEmbedder(ABC):
    """Defines the interface that all embedding implementations must satisfy.

    Implementations may be backed by a local sentence-transformer model, a
    remote API (Bedrock, OpenAI, Cohere …), or a cached wrapper around any
    of the above.
    """

    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of text strings.

        Args:
            texts: Non-empty list of strings to embed.

        Returns:
            List of embedding vectors (one per input string), each represented
            as a ``List[float]``.  The order matches the input order.

        Raises:
            ValueError: If *texts* is empty.
            RuntimeError: On model or API failure.
        """
        ...
