"""
OpenTelemetry SDK initialisation.

Called once at process start, before any FastAPI/ASGI instrumentation is
applied.  Kept as a standalone module so main.py stays readable.
"""

from __future__ import annotations

import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger(__name__)


def init_telemetry() -> None:
    """Configure and register the global TracerProvider."""
    from api.config import settings  # local import avoids circular deps at module load

    resource = Resource.create(
        {
            "service.name": "mcp-security-api",
            "service.version": settings.app_version,
            "deployment.environment": "production" if not settings.debug else "development",
        }
    )

    exporter = OTLPSpanExporter(
        endpoint=settings.otlp_endpoint,
        insecure=settings.otlp_insecure,
    )

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    logger.info(
        "OpenTelemetry initialised – exporting to %s", settings.otlp_endpoint
    )
