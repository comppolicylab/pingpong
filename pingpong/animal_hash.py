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


def process_threads(
    threads: list[Thread], user_id: int, is_supervisor_dict: dict[int, bool]
) -> list[ThreadSchema]:
    for new_thread in threads:
        if new_thread.assistant_id:
            new_thread.assistant_names = {
                new_thread.assistant_id: new_thread.assistant.name
            }
        else:
            new_thread.assistant_names = {0: "Deleted Assistant"}
        new_thread.user_names = user_names(
            new_thread, user_id, is_supervisor_dict.get(new_thread.class_id, False)
        )
    return threads


def name(user: User) -> str:
    """Return some kind of name for the user."""
    if user.display_name:
        return user.display_name
    parts = [name for name in [user.first_name, user.last_name] if name]
    if not parts:
        return user.email
    return " ".join(parts)


def user_names(new_thread: Thread, user_id: int, is_supervisor=False) -> list[str]:
    return [
        "Me"
        if u.id == user_id
        else name(u)
        if is_supervisor and new_thread.display_user_info
        else pseudonym(new_thread, u)
        if not new_thread.private
        else "Anonymous User"
        for u in new_thread.users
    ]
