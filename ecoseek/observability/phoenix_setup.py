"""
AAR-06 / AAR-07: Phoenix / Arize observability setup.

Initialises the OpenTelemetry tracer that all AAR modules use.
If ``arize-phoenix`` is not installed or ``PHOENIX_ENDPOINT`` is unset,
the tracer degrades to a no-op so the AAR loop still works without
observability infrastructure.

Span naming convention (AAR-07)
-------------------------------
- ``aar.orchestrate``       – root span for the full AAR cycle
- ``aar.intent_decompose``  – intent decomposer call
- ``aar.retrieve.{tool}``   – one retrieval tool invocation
- ``aar.assess``            – quality assessor call
- ``aar.gate``              – adaptive decision gate
- ``aar.synthesize``        – final synthesis call
"""

import os
import logging
from typing import Optional

logger = logging.getLogger("ecoseek.observability")

_tracer = None
_initialised = False


class _NoOpSpan:
    """Fallback span when Phoenix/OTel is unavailable."""

    def set_attribute(self, key: str, value) -> None:
        pass

    def end(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _NoOpTracer:
    """Fallback tracer that returns no-op spans."""

    def start_span(self, name: str = "", attributes: Optional[dict] = None) -> _NoOpSpan:
        return _NoOpSpan()

    def start_as_current_span(self, name: str = "", attributes: Optional[dict] = None):
        return _NoOpSpan()


def init_phoenix() -> None:
    """
    Attempt to initialise Phoenix tracing.

    Reads ``PHOENIX_ENDPOINT`` (defaults to ``http://localhost:6006``) and
    ``PHOENIX_PROJECT_NAME`` (defaults to ``ecoseek``).

    Safe to call multiple times — only initialises once.
    """
    global _tracer, _initialised

    if _initialised:
        return
    _initialised = True

    endpoint = os.getenv("PHOENIX_ENDPOINT", "")
    project = os.getenv("PHOENIX_PROJECT_NAME", "ecoseek")

    if not endpoint:
        logger.info("PHOENIX_ENDPOINT not set — AAR tracing in no-op mode")
        _tracer = _NoOpTracer()
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor

        # Phoenix uses OTLP/HTTP exporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("ecoseek", schema_url=project)
        logger.info("Phoenix tracing initialised → %s (project=%s)", endpoint, project)
    except ImportError as exc:
        logger.warning("Phoenix/OTel packages not installed (%s) — no-op mode", exc)
        _tracer = _NoOpTracer()
    except Exception as exc:
        logger.warning("Failed to init Phoenix tracing (%s) — no-op mode", exc)
        _tracer = _NoOpTracer()


def get_tracer():
    """Return the global tracer (initialises lazily on first call)."""
    global _tracer
    if _tracer is None:
        init_phoenix()
    return _tracer
