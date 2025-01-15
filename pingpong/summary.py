import openai
import pingpong.models as models

from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from pingpong.schemas import (
    AIAssistantSummary,
    AssistantSummary,
    AssistantSummaries,
    ThreadUserMessages,
)


async def generate_assistant_summaries(
    cli: openai.AsyncClient,
    session: AsyncSession,
    class_id: int,
    after: datetime | None = None,
) -> AssistantSummaries:
    summaries = list[AssistantSummary]()

    # Get all assistants for the class
    async for assistant_id in models.Assistant.async_get_by_class_id(
        session=session, class_id=class_id
    ):
        user_messages_list = list[ThreadUserMessages]()
        async for thread in models.Thread.get_threads_by_assistant_id(
            session=session, assistant_id=assistant_id, after=after
        ):
            user_messages_list.append(
                ThreadUserMessages(
                    id=thread.id,
                    thread_id=thread.thread_id,
                    user_messages=await get_thread_user_messages(cli, thread.thread_id),
                )
            )

        assistant_summary = await generate_thread_summary(cli, user_messages_list)
        summaries.append(
            AssistantSummary(
                assistant_id=assistant_id,
                questions=assistant_summary.questions if assistant_summary else [],
            )
        )

    return AssistantSummaries(assistant_summaries=summaries, class_id=class_id)


async def get_thread_user_messages(
    cli: openai.AsyncClient, thread_id: str
) -> list[str]:
    messages = await cli.beta.threads.messages.list(thread_id, limit=10, order="asc")

    user_messages = list[str]()
    for message in messages.data:
        for content in message.content:
            if message.role == "user":
                if content.type == "text":
                    user_messages.append(
                        f"{' '.join(content.text.value.split()[:100])}"
                    )
                if content.type in ["image_file", "image_url"]:
                    user_messages.append("User uploaded an image file")
    return user_messages


summarization_prompt = """
Extract key questions or ideas from a list of user queries in chatbot threads provided in the specified XML schema. If there are no valuable questions or threads for an assistant, do not return any results.

# Input Format

The user threads will be provided in the following XML schema:

```xml
<thread>
    <id>254</id>
    <messages>
        <message>User message 1</message>
        <message>User message 2</message>
    </messages>
</thread>
```

# Steps

1. **Identify Key Questions/Ideas**: Examine the list of query threads to recognize recurring themes or questions that students have asked.

2. **Select Representative Quotes**: For each identified question or idea, select up to three representative quotes from the messages that encapsulate the essence of the question or idea.

3. **Gather Thread IDs**: Record the thread IDs associated with the selected quotes to track the context and source of each significant question or idea.

4. **Organize and Limit**: Structure the findings into a JSON format as specified and limit the number of questions to a maximum of 10, and the representative threads per question to a maximum of 3.

5. **Check for Results**: Ensure there are threads with valuable questions before returning results. If no such threads or questions exist, return nothing.

# Output Format

The output must be structured as a JSON object conforming to the provided responseFormat class. If no valuable questions or threads are found, return an empty array.

# Notes

- Ensure each entry in "questions" accurately reflects the student queries.
- Each "question" should be concise, distinctly capturing the theme or query without extraneous detail.
- Quotes should accurately capture the essence of the student's question or idea and relate directly to the question identified.
- Adhere to class constraints: max 10 questions and max 3 threads per question to ensure the JSON remains valid.
- Do not output any JSON if there are no valuable questions or threads.
"""


def generate_thread_xml(thread_messages: list[ThreadUserMessages]) -> str:
    """
    Generate an XML string from a list of thread messages.

    Format:
    <thread>
        <id>254</id>
        <messages>
            <message>User message 1</message>
            <message>User message 2</message>
        </messages>
    </thread>
    """

    xml = ""
    for thread in thread_messages:
        xml += f"<thread><id>{thread.id}</id><messages>"
        for message in thread.user_messages:
            xml += f"<message>{message}</message>"
        xml += "</messages></thread>\n"
    return xml


async def generate_thread_summary(
    cli: openai.AsyncClient, thread_messages: list[ThreadUserMessages]
) -> AIAssistantSummary | None:
    completion = await cli.beta.chat.completions.parse(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": summarization_prompt},
            {"role": "user", "content": generate_thread_xml(thread_messages)},
        ],
        response_format=AIAssistantSummary,
    )

    return completion.choices[0].message.parsed
