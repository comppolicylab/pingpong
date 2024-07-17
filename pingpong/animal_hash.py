from .names import adjectives, names
from .models import Thread, User
from .schemas import Thread as ThreadSchema
from typing import TypeVar
import mmh3

T = TypeVar("T")


def list_p(A: list[T], pct: float) -> T:
    return A[int(pct * len(A))]


uint64_max = 2**64


def animal_hash(input: str) -> str:
    x, y = mmh3.hash64(input, signed=False)

    adj = list_p(adjectives, x / uint64_max)
    animal = list_p(names, y / uint64_max)
    return f"{adj.capitalize()} {animal.capitalize()}"


def pseudonym(thread: Thread, user: User) -> str:
    return animal_hash(f"{thread.id}-{user.id}-{user.created}")


def process_threads(threads: list[Thread], user_id: int) -> list[ThreadSchema]:
    for new_thread in threads:
        new_thread.assistant_names = {
            new_thread.assistant_id: new_thread.assistant.name
        }
        new_thread.user_names = user_names(new_thread, user_id)
    return threads


def user_names(new_thread: Thread, user_id: int) -> list[str]:
    return [
        "Me"
        if u.id == user_id
        else pseudonym(new_thread, u)
        if not new_thread.private
        else "Anonymous User"
        for u in new_thread.users
    ]
