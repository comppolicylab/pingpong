from openai.types.beta.threads.runs import RunStep
from openai.pagination import AsyncCursorPage


async def process_run_steps(run_steps: AsyncCursorPage[RunStep], last_message_id: str):
    messages = []
    async for step in run_steps:
        match step.type:
            case "tool_calls":
                for tool_call in step.step_details.tool_calls:
                    if tool_call.type == "code_interpreter":
                        new_message = {
                            "id": tool_call.id,
                            "assistant_id": step.assistant_id,
                            "created_at": step.created_at,
                            "content": [
                                {
                                    "code": tool_call.code_interpreter.input,
                                    "type": "code",
                                }
                            ],
                            "file_search_file_ids": [],
                            "code_interpreter": [],
                            "metadata": {},
                            "object": "thread.message",
                            "role": "assistant",
                            "run_id": step.run_id,
                            "thread_id": step.thread_id,
                        }
                        for output in tool_call.code_interpreter.outputs:
                            if output.type == "image":
                                new_message["content"].append(
                                    {
                                        "image_file": {"file_id": output.image.file_id},
                                        "type": "code_output_image_file",
                                    }
                                )
                        messages.append(new_message)
            case "message_creation":
                if step.step_details.message_creation.message_id == last_message_id:
                    return messages, True
    return messages, False
