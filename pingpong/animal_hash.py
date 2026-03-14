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
        if len(new_thread.anonymous_sessions) > 0:
            new_thread.anonymous_session = True
        new_thread.is_current_user_participant = False
        for user in new_thread.users:
            if user.id == user_id:
                new_thread.is_current_user_participant = True
    return threads


def name(user: User) -> str:
    """Return some kind of name for the user."""
    if user.display_name:
        return user.display_name
    parts = [name for name in [user.first_name, user.last_name] if name]
    if not parts:
        return user.email
    return " ".join(parts)


def display_name_for_thread_user(
    thread: Thread,
    actor_user_id: int | None,
    users: dict[int, User],
    *,
    current_user_ids: list[int],
    is_supervisor: bool,
) -> str | None:
    if actor_user_id is None:
        return None
    if actor_user_id in current_user_ids:
        return "Me"
    user = users.get(actor_user_id)
    if user is None:
        return "Unknown User"
    if thread.display_user_info and is_supervisor:
        return name(user)
    if thread.private:
        return "Anonymous User"
    return pseudonym(thread, user)


def user_names(new_thread: Thread, user_id: int, is_supervisor=False) -> list[str]:
    names: list[str] = []
    for u in new_thread.users:
        if u.anonymous_link_id and u.id != user_id:
            continue
        display_name = display_name_for_thread_user(
            new_thread,
            u.id,
            {u.id: u},
            current_user_ids=[user_id],
            is_supervisor=is_supervisor,
        )
        if display_name is not None:
            names.append(display_name)
    return names
