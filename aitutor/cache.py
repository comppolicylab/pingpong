import json
import os
from functools import wraps
from typing import Callable, Generic, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


class _LocalCacheWrapper(Generic[P, R]):
    def __init__(
        self,
        f: Callable[P, R],
        cache_dir: str,
        key: Callable[P, str] | None = None,
        ser: Callable[[R], str] | None = None,
        de: Callable[[str], R] | None = None,
    ):
        self.f = f
        self.cache_dir = cache_dir
        self.key = key
        self.ser = ser
        self.de = de

    def _get_dest(self, *args: P.args, **kwargs: P.kwargs) -> str:
        """Get disk location for cached result."""
        if not self.key:
            cache_parts = [str(v) for v in args] + [
                f"{k}:{str(v)}" for k, v in kwargs.items()
            ]
            dest = ",".join(cache_parts)
        else:
            dest = self.key(*args, **kwargs)
        return os.path.join(self.cache_dir, f"{dest}.json")

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R:
        """Call the target function with caching."""
        dest = self._get_dest(*args, **kwargs)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.exists(dest):
            with open(dest, "r") as fh:
                raw = fh.read()
                return self.de(raw) if self.de else json.loads(raw)
        result = self.f(*args, **kwargs)
        with open(dest, "w") as fh:
            as_str = self.ser(result) if self.ser else json.dumps(result)
            fh.write(as_str)
        return result

    def evict(self, *args: P.args, **kwargs: P.kwargs) -> bool:
        """Remove cached result.

        Returns:
            Whether cached copy was removed.
        """
        dest = self._get_dest(*args, **kwargs)
        if not os.path.exists(dest):
            return False
        os.remove(dest)
        return True


def persist(
    cache_dir: str,
    key: Callable[P, str] | None = None,
    ser: Callable[[R], str] | None = None,
    de: Callable[[str], R] | None = None,
) -> Callable[[Callable[P, R]], _LocalCacheWrapper[P, R]]:
    """Persistent (on-disk) memoize decorator."""
    os.makedirs(cache_dir, exist_ok=True)

    def dec(f: Callable[P, R]) -> _LocalCacheWrapper[P, R]:
        cache = _LocalCacheWrapper(f, cache_dir, key, ser, de)
        return wraps(f)(cache)

    return dec
