from contextlib import contextmanager

from azure.monitor.opentelemetry import configure_azure_monitor

from .config import config
from .otel import AsyncGauge, Counter, Gauge, Histogram

inbound_messages = Counter(
    "inbound_messages",
    "Number of inbound messages from users on Slack",
    unit="msg",
    labels=["workspace", "channel", "user"],
)


replies = Counter(
    "replies",
    "Number of replies sent to users on Slack",
    unit="msg",
    labels=["workspace", "channel", "user"],
)


reply_duration = Histogram(
    "reply_duration",
    "Duration of replies",
    unit="s",
    labels=["relevant", "success", "workspace", "channel"],
)


engine_quota = AsyncGauge(
    "engine_quota", "Token quota usage for the engine", unit="tokens", labels=["engine"]
)


engine_usage = Histogram(
    "engine_usage",
    "Token usage for user requests",
    unit="tokens",
    labels=["direction", "model", "engine", "workspace", "channel", "user"],
)


in_flight = Gauge(
    "in_flight",
    "Number of in-flight requests",
    unit="requests",
    labels=["app"],
)


event_count = Counter(
    "event_count",
    "Number of events processed",
    unit="events",
    labels=["app", "event_type", "success", "workspace", "channel_type", "channel"],
)


@contextmanager
def metrics():
    if config.metrics.connection_string:
        configure_azure_monitor(
            connection_string=config.metrics.connection_string,
        )
    yield
