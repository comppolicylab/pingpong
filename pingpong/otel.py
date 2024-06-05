"""Compatibility layer for OpenTelemetry metrics to Prometheus-style metrics.

Allows instrumentation with Prometheus-style syntax but using OpenTelemetry
on the backend.
"""

from typing import Callable

from opentelemetry import metrics
from opentelemetry.metrics import CallbackOptions, Observation


class PartialProxy:
    def __init__(self, obj, *args, **kwargs):
        self._obj = obj
        self._args = args
        self._kwargs = kwargs

    def __getattr__(self, name):
        # If the attribute is a method, return a partially applied method
        # with the arguments and keyword arguments already applied.
        attr = getattr(self._obj, name)
        if callable(attr):
            return lambda *args, **kwargs: attr(
                *self._args, *args, **self._kwargs, **kwargs
            )
        return attr


class Metric:
    @property
    def meter(self):
        return metrics.get_meter_provider().get_meter(__name__)

    def check_labels(self, **kwargs):
        if set(kwargs.keys()) != set(self._labels):
            raise ValueError(f"Expected labels {self._labels}, got {kwargs.keys()}")

    def labels(self, **kwargs):
        """This exists for compatibility with the Prometheus client."""
        return PartialProxy(self, **kwargs)


class Gauge(Metric):
    def __init__(
        self,
        name: str,
        description: str,
        unit: str | None = None,
        labels: list[str] | None = None,
    ):
        self._labels = labels or []
        self._values = dict[frozenset[tuple[str, str]], float]()
        self._gauge = self.meter.create_observable_gauge(
            name, callbacks=[self._report], description=description, unit=unit
        )

    def set(self, value: float, **kwargs):
        self.check_labels(**kwargs)
        self._values[frozenset(kwargs.items())] = value

    def inc(self, value: float = 1.0, **kwargs):
        self.check_labels(**kwargs)
        key = frozenset(kwargs.items())
        self._values[key] = self._values.get(key, 0.0) + value

    def dec(self, value: float = 1.0, **kwargs):
        self.check_labels(**kwargs)
        key = frozenset(kwargs.items())
        self._values[key] = self._values.get(key, 0.0) - value

    def _report(self, _: CallbackOptions):
        for labels, value in self._values.items():
            yield Observation(value, dict(labels))


AsyncGaugeCallback = Callable[[], tuple[float, dict[str, str]]]


class AsyncGauge(Metric):
    def __init__(
        self,
        name: str,
        description: str,
        callbacks: list[AsyncGaugeCallback] | None = None,
        unit: str | None = None,
        labels: list[str] | None = None,
    ):
        self._labels = labels or []
        self._callbacks = callbacks or []
        self._gauge = self.meter.create_observable_gauge(
            name, callbacks=[self._invoke], description=description, unit=unit
        )

    def _invoke(self, _: CallbackOptions):
        for callback in self._callbacks:
            val, attrs = callback()
            yield Observation(val, attrs)

    def monitor(self, callback: AsyncGaugeCallback):
        self._callbacks.append(callback)


class Histogram(Metric):
    def __init__(
        self,
        name: str,
        description: str,
        unit: str | None = None,
        labels: list[str] | None = None,
    ):
        self._labels = labels or []
        self._histogram = self.meter.create_histogram(
            name, description=description, unit=unit
        )

    def observe(self, value: float, **kwargs):
        self.check_labels(**kwargs)
        self._histogram.record(value, kwargs)


class Counter(Metric):
    def __init__(
        self,
        name: str,
        description: str,
        unit: str | None = None,
        labels: list[str] | None = None,
    ):
        self._labels = labels or []
        self._counter = self.meter.create_counter(
            name, description=description, unit=unit
        )

    def inc(self, value: float = 1.0, **kwargs):
        self.check_labels(**kwargs)
        self._counter.add(value, kwargs)

    def dec(self, value: float = 1.0, **kwargs):
        self.check_labels(**kwargs)
        self._counter.add(-value, kwargs)
