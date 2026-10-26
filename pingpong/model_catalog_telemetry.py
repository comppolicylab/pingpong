"""Sentry observations for enabled model-catalog lookups only."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from time import perf_counter

import sentry_sdk
from sentry_sdk import metrics


@dataclass
class CatalogObservation:
    operation: str
    provider: str
    outcome: str = "unavailable"
    reason: str = "none"

    def attributes(self):
        return {
            "catalog.operation": self.operation,
            "catalog.provider": self.provider,
            "catalog.outcome": self.outcome,
            "catalog.reason": self.reason,
        }


_current: ContextVar[CatalogObservation | None] = ContextVar(
    "model_catalog_observation", default=None
)


@contextmanager
def lookup(operation: str, provider: str):
    # Bound standalone transactions to the lookup, including on voice startup.
    start = (
        sentry_sdk.start_transaction
        if sentry_sdk.get_current_span() is None
        else sentry_sdk.start_span
    )
    with start(op="model_catalog.lookup", name="model_catalog.lookup") as span:
        observation = CatalogObservation(operation, provider)
        token = _current.set(observation)
        started = perf_counter()
        try:
            yield observation
        except BaseException:
            observation.outcome = "error"
            if observation.reason == "none":
                observation.reason = "error"
            raise
        finally:
            attributes = observation.attributes()
            for key, value in attributes.items():
                span.set_data(key, value)
            span.set_data("cache.hit", observation.outcome == "hit")
            metrics.distribution(
                "model_catalog.lookup.duration",
                (perf_counter() - started) * 1000,
                unit="millisecond",
                attributes=attributes,
            )
            metrics.count("model_catalog.lookups", 1, attributes=attributes)
            _current.reset(token)


def outcome(value: str, reason: str | None = None) -> None:
    observation = _current.get()
    if observation is not None:
        observation.outcome = value
        if reason is not None:
            observation.reason = reason


def event(name: str) -> None:
    observation = _current.get()
    if observation is not None:
        metrics.count(f"model_catalog.{name}", 1, attributes=observation.attributes())


@contextmanager
def step(name: str):
    observation = _current.get()
    if observation is None:
        yield
        return
    with sentry_sdk.start_span(
        op=f"model_catalog.{name}", name=f"model_catalog.{name}"
    ) as span:
        started = perf_counter()
        result = "ok"
        try:
            yield
        except BaseException:
            result = "error"
            raise
        finally:
            attributes = {
                "catalog.operation": observation.operation,
                "catalog.provider": observation.provider,
                "catalog.outcome": result,
            }
            for key, value in attributes.items():
                span.set_data(key, value)
            if name == "redis_read":
                span.set_data("cache.operation", "get")
            metrics.distribution(
                f"model_catalog.{name}.duration",
                (perf_counter() - started) * 1000,
                unit="millisecond",
                attributes=attributes,
            )
            metrics.count(f"model_catalog.{name}.calls", 1, attributes=attributes)


def decision(provider: str, value: str, reason: str = "none") -> None:
    metrics.count(
        "model_catalog.runtime.decisions",
        1,
        attributes={
            "catalog.operation": "runtime",
            "catalog.provider": provider,
            "catalog.decision": value,
            "catalog.reason": reason,
        },
    )
