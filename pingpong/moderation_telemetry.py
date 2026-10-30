"""Sentry timing for input moderation and its provider calls."""

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from time import perf_counter

import sentry_sdk
from sentry_sdk import metrics


@dataclass
class ModerationObservation:
    provider: str
    outcome: str = "error"
    reason: str = "internal_error"

    def attributes(self):
        return {
            "moderation.provider": self.provider,
            "moderation.outcome": self.outcome,
            "moderation.reason": self.reason,
        }


@contextmanager
def measure(operation: str, provider: str):
    name = f"moderation.{operation}"
    start = (
        sentry_sdk.start_transaction
        if sentry_sdk.get_current_span() is None
        else sentry_sdk.start_span
    )
    with start(op=name, name=name) as span:
        observation = ModerationObservation(provider)
        started = perf_counter()
        try:
            yield observation
        except asyncio.CancelledError:
            observation.outcome = "cancelled"
            observation.reason = "cancelled"
            raise
        finally:
            attributes = observation.attributes()
            for key, value in attributes.items():
                span.set_data(key, value)
            metrics.distribution(
                f"{name}.duration",
                (perf_counter() - started) * 1000,
                unit="millisecond",
                attributes=attributes,
            )
            metrics.count(f"{name}.calls", 1, attributes=attributes)
