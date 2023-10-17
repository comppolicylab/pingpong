import json
import os
from functools import wraps
from typing import Callable


def persist(
    cache_dir: str,
    key: Callable | None = None,
    ser: Callable | None = None,
    de: Callable | None = None,
):
    """Persistent (on-disk) memoize decorator."""
    os.makedirs(cache_dir, exist_ok=True)

    def dec(f: Callable):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not key:
                cache_parts = [str(v) for v in args] + [
                    f"{k}:{str(v)}" for k, v in kwargs.items()
                ]
                dest = ",".join(cache_parts)
            else:
                dest = key(*args, **kwargs)

            dest = os.path.join(cache_dir, f"{dest}.json")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if os.path.exists(dest):
                with open(dest, "r") as fh:
                    raw = json.load(fh)
                    return de(raw) if de else raw
            result = f(*args, **kwargs)
            with open(dest, "w") as fh:
                json.dump(ser(result) if ser else result, fh)
            return result

        return wrapped

    return dec
