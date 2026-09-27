"""Amazon Bedrock Titan Embed Text v2 embedder."""

from __future__ import annotations

import json
import logging
from typing import List

import boto3

from .base import BaseEmbedder

logger = logging.getLogger(__name__)

_MODEL_ID = "amazon.titan-embed-text-v2:0"
_CONTENT_TYPE = "application/json"
_ACCEPT = "application/json"

# Titan Embed Text v2 supports 256 / 512 / 1024 output dimensions.
# Default to 1024, which is the model's native maximum.
_DEFAULT_DIMENSIONS = 1024


class BedrockEmbedder(BaseEmbedder):
    """Embedder backed by Amazon Bedrock's Titan Embed Text v2 model.

    Each text is embedded in a separate synchronous ``InvokeModel`` call.
    Bedrock does not support batch embedding in a single API call for this
    model, so large batches will be slower than local models.

    Args:
        region:     AWS region for the Bedrock runtime endpoint.
        dimensions: Output vector dimensionality — must be 256, 512, or 1024.
        normalize:  Whether to L2-normalise output vectors.
    """

    def __init__(
        self,
        region: str = "us-east-1",
        dimensions: int = _DEFAULT_DIMENSIONS,
        normalize: bool = True,
    ) -> None:
        if dimensions not in {256, 512, 1024}:
            raise ValueError(
                f"Titan Embed Text v2 supports dimensions 256, 512, or 1024; got {dimensions}"
            )
        self.region = region
        self.dimensions = dimensions
        self.normalize = normalize
        self._client = None

    def _get_client(self):
        if self._client is None:
            self._client = boto3.client("bedrock-runtime", region_name=self.region)
        return self._client

    def _embed_one(self, text: str) -> List[float]:
        client = self._get_client()
        body = json.dumps(
            {
                "inputText": text,
                "dimensions": self.dimensions,
                "normalize": self.normalize,
            }
        )
        response = client.invoke_model(
            modelId=_MODEL_ID,
            body=body,
            contentType=_CONTENT_TYPE,
            accept=_ACCEPT,
        )
        data = json.loads(response["body"].read())
        return data["embedding"]

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Embed each text via Bedrock InvokeModel.

        Raises:
            ValueError: If *texts* is empty.
            botocore.exceptions.ClientError: On API failure.
        """
        if not texts:
            raise ValueError("embed() requires a non-empty list of texts.")

        embeddings: List[List[float]] = []
        for i, text in enumerate(texts):
            try:
                vec = self._embed_one(text)
                embeddings.append(vec)
            except Exception:
                logger.exception(
                    "Bedrock embed failed for text index %d (len=%d)", i, len(text)
                )
                raise

        return embeddings
