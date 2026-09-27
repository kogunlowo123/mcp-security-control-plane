"""
OpenTelemetry tracing middleware.

Creates a parent span for each HTTP request, propagates W3C TraceContext from
incoming headers, and stores the trace_id on ``request.state.trace_id`` so
that route handlers and other middleware can attach it to audit records,
CloudEvents, and log fields.

The trace_id placed on request.state comes from the active OTel span context
so that all downstream spans, audit records, and CloudEvents share the same
identifier with the distributed trace.
"""

from __future__ import annotations

import logging

from opentelemetry import context as otel_context
from opentelemetry import propagate, trace
from opentelemetry.trace import StatusCode
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

_TRACER = trace.get_tracer(__name__, schema_url="https://opentelemetry.io/schemas/1.24.0")

# Header name used to expose the trace_id to API consumers
TRACE_ID_HEADER = "X-Trace-ID"


def _format_trace_id(trace_id_int: int) -> str:
    """Convert the 128-bit integer trace_id to a 32-character hex string."""
    return format(trace_id_int, "032x")


class TracingMiddleware(BaseHTTPMiddleware):
    """
    Wrap each request in an OpenTelemetry span.

    - Extracts W3C TraceContext / Baggage from incoming HTTP headers.
    - Creates a server span named ``<METHOD> <path>``.
    - Attaches ``http.*`` attributes to the span.
    - Stores the trace_id (hex string) on ``request.state.trace_id``.
    - Adds ``X-Trace-ID`` to the response headers.
    - Marks the span as ERROR on HTTP 5xx responses.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Extract trace context from incoming headers (W3C traceparent etc.)
        carrier = dict(request.headers)
        ctx = propagate.extract(carrier)
        token = otel_context.attach(ctx)

        span_name = f"{request.method} {request.url.path}"

        try:
            with _TRACER.start_as_current_span(
                span_name,
                kind=trace.SpanKind.SERVER,
            ) as span:
                # Capture trace_id from the span that was just created
                span_ctx = span.get_span_context()
                if span_ctx.is_valid:
                    trace_id_hex = _format_trace_id(span_ctx.trace_id)
                else:
                    # No valid span (e.g. no-op tracer) – generate a fallback
                    import uuid
                    trace_id_hex = uuid.uuid4().hex

                request.state.trace_id = trace_id_hex

                # Standard HTTP semantic conventions
                span.set_attribute("http.method", request.method)
                span.set_attribute("http.url", str(request.url))
                span.set_attribute("http.scheme", request.url.scheme)
                span.set_attribute("http.target", request.url.path)
                span.set_attribute("http.host", request.url.hostname or "")
                span.set_attribute("http.flavor", "1.1")
                span.set_attribute("net.peer.ip", request.client.host if request.client else "")

                try:
                    response: Response = await call_next(request)
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(StatusCode.ERROR, str(exc))
                    raise

                span.set_attribute("http.status_code", response.status_code)
                if response.status_code >= 500:
                    span.set_status(StatusCode.ERROR, f"HTTP {response.status_code}")
                else:
                    span.set_status(StatusCode.OK)

                # Propagate trace_id to the response so callers can correlate
                response.headers[TRACE_ID_HEADER] = trace_id_hex
                return response
        finally:
            otel_context.detach(token)
