import os
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from openinference.instrumentation.google_adk import GoogleADKInstrumentor


def setup_telemetry() -> None:
    """
    Call once before creating any agents or runners.
    If OTEL_EXPORTER_OTLP_TRACES_ENDPOINT is not set, silently skips.
    When set, exports all ADK agent/tool spans to the OTLP endpoint.
    GoogleADKInstrumentor auto-patches all ADK agent calls — no per-agent opt-in needed.
    """
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if not endpoint:
        return

    resource = Resource.create({
        "service.name": os.getenv("OTEL_SERVICE_NAME", "agent-mesh"),
        "service.version": "0.1.0",
    })
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
    )
    trace.set_tracer_provider(provider)
    GoogleADKInstrumentor().instrument()
