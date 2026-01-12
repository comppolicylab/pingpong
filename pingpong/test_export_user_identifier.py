from datetime import datetime, timedelta, timezone

from pingpong import models
from pingpong.ai import export_user_identifier, generate_user_hash


NOW = datetime(2024, 1, 1, tzinfo=timezone.utc)


def make_user(user_id: int, name: str | None) -> models.User:
    user = models.User(
        id=user_id,
        display_name=name,
        first_name=None,
        last_name=None,
        email=f"user{user_id}@example.com",
        created=NOW + timedelta(minutes=user_id),
    )
    return user


def make_class(is_private: bool) -> models.Class:
    return models.Class(id=1, name="Test Class", private=is_private, created=NOW)


def test_export_user_identifier_shows_names_when_allowed():
    class_ = make_class(is_private=False)
    users = [
        make_user(1, "Ada"),
        models.User(
            id=2,
            first_name="Alan",
            last_name="Turing",
            email="user2@example.com",
            created=NOW + timedelta(minutes=2),
        ),
    ]
    thread = models.Thread(display_user_info=True, private=False, users=users)

    assert export_user_identifier(thread, class_) == "Ada, Alan Turing"


def test_export_user_identifier_hashes_when_display_info_disabled():
    class_ = make_class(is_private=False)
    users = [make_user(1, "Ada"), make_user(2, "Grace")]
    thread = models.Thread(display_user_info=False, private=False, users=users)

    expected = ", ".join(generate_user_hash(class_, user) for user in users)
    assert export_user_identifier(thread, class_) == expected


def test_export_user_identifier_hashes_when_private():
    users = [make_user(1, "Ada"), make_user(2, "Grace")]

    class_private = make_class(is_private=True)
    thread = models.Thread(display_user_info=True, private=False, users=users)
    expected = ", ".join(generate_user_hash(class_private, user) for user in users)
    assert export_user_identifier(thread, class_private) == expected

    class_public = make_class(is_private=False)
    thread_private = models.Thread(display_user_info=True, private=True, users=users)
    assert export_user_identifier(thread_private, class_public) == "Ada, Grace"


def test_export_user_identifier_empty_users_returns_unknown():
    class_ = make_class(is_private=False)
    thread = models.Thread(display_user_info=True, private=False, users=[])

    assert export_user_identifier(thread, class_) == "Unknown user"
