from .names import adjectives, names
from typing import TypeVar
import mmh3

T = TypeVar('T')

def list_p(A: list[T], pct: float) -> T:
    return A[int(pct * len(A))]

uint64_max = 2**64

def animal_hash(input: str) -> str:
    x, y = mmh3.hash64(input, signed=False)

    adj = list_p(adjectives, x / uint64_max)
    animal = list_p(names, y / uint64_max)
    return f"{adj.capitalize()} {animal.capitalize()}"