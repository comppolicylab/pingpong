from contextlib import contextmanager

from .otel import Counter, Gauge, Histogram

api_requests = Counter(
    "api_requests",
    "Number of requests to the API",
    unit="requests",
    labels=["app", "route", "method", "status"],
)


api_request_duration = Histogram(
    "api_request_duration",
    "Duration of requests to the API",
    unit="s",
    labels=["app", "route", "method", "status"],
)


inbound_messages = Counter(
    "inbound_messages",
    "Number of inbound messages from users on the app",
    unit="msg",
    labels=["app", "class_", "user", "thread"],
)


in_flight = Gauge(
    "in_flight",
    "Number of in-flight requests",
    unit="requests",
    labels=["app"],
)


@contextmanager
def metrics():
    # TODO - set up for AWS
    yield
