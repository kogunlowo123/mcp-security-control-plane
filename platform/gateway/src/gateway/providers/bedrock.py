"""Bedrock provider for LLM calls through the gateway."""

from __future__ import annotations

import json
import os
from typing import Any

import boto3


class BedrockProvider:
    """Invokes Bedrock foundation models on behalf of authenticated agents."""

    def __init__(self, region: str | None = None) -> None:
        self._region = region or os.getenv("AWS_REGION", "us-east-1")
        self._client = boto3.client("bedrock-runtime", region_name=self._region)

    def invoke(
        self,
        model_id: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """Invoke a Bedrock model and return the response."""
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        })

        response = self._client.invoke_model(
            modelId=model_id,
            body=body,
            contentType="application/json",
            accept="application/json",
        )

        result = json.loads(response["body"].read())
        return {
            "content": result["content"][0]["text"],
            "stop_reason": result.get("stop_reason"),
            "usage": result.get("usage", {}),
            "model_id": model_id,
        }
