from sqlalchemy import select

import pingpong.models as models
from ..authz.base import AuthzClient


async def delete_thread(session, authz: AuthzClient, thread: models.Thread) -> None:
    tokens = (
        await session.scalars(
            select(models.AnonymousSession.session_token).where(
                models.AnonymousSession.thread_id == thread.id
            )
        )
    ).all()
    await thread.delete(session)
    await authz.write_safe(
        revoke=[
            (f"class:{thread.class_id}", "parent", f"thread:{thread.id}"),
            *(
                tuple_
                for token in tokens
                for tuple_ in (
                    (
                        f"anonymous_user:{token}",
                        "anonymous_party",
                        f"thread:{thread.id}",
                    ),
                    (
                        f"anonymous_user:{token}",
                        "can_view",
                        f"assistant:{thread.assistant_id}",
                    ),
                )
            ),
        ]
    )
