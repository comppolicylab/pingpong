import pingpong.models as models

from pingpong.schemas import CodeInterpreterMessage
from sqlalchemy.ext.asyncio import AsyncSession


async def get_placeholder_ci_calls(
    session: AsyncSession,
    assistant_id: str,
    thread_id: str,
    thread_obj_id: int,
    after: int,
    before: int | None = None,
) -> list[CodeInterpreterMessage]:
    """
    Get placeholder code interpreter calls for a thread.

    Args:
        session (AsyncSession): SQLAlchemy session
        assistant_id (str): assistant id
        thread_id (str): thread id
        thread_obj_id (int): thread object id
        after (int): timestamp of message after which to get the calls (measured by the created_at field of the message)
        before (int | None): timestamp of message before which to get the calls (measured by the created_at field of the message)
        desc (bool): whether to sort the calls in descending order

    Returns:
        list[CodeInterpreterMessage]: list of placeholder code interpreter calls
    """
    placeholder_code_interpreter_calls = []
    async for tool_call in models.CodeInterpreterCall.get_calls(
        session=session, thread_id=thread_obj_id, after=after, before=before
    ):
        new_message = CodeInterpreterMessage.model_validate(
            {
                "id": str(tool_call.id),
                "assistant_id": assistant_id,
                "created_at": float(
                    tool_call.created_at
                ),  # Comes from OpenAI API as seconds
                "content": [
                    {
                        "run_id": tool_call.run_id,
                        "step_id": tool_call.step_id,
                        "thread_id": thread_id,
                        "type": "code_interpreter_call_placeholder",
                    }
                ],
                "file_search_file_ids": [],
                "code_interpreter": [],
                "metadata": {
                    "step_id": tool_call.step_id,
                },
                "object": "code_interpreter_call_placeholder",
                "role": "assistant",
                "run_id": tool_call.run_id,
                "thread_id": thread_id,
            }
        )
        placeholder_code_interpreter_calls.append(new_message)
    return placeholder_code_interpreter_calls
