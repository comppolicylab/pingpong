import openai
from pingpong.auth import generate_auth_link
from pingpong.config import config
from pingpong.invite import send_summary
import pingpong.models as models

from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from pingpong.now import utcnow, NowFn
from pingpong.schemas import (
    AIAssistantSummary,
    AIAssistantSummaryOutput,
    AssistantSummary,
    ClassSummary,
    ClassSummaryExport,
    QuestionSummary,
    ThreadUserMessages,
    ThreadsToSummarize,
)


async def export_class_summary(
    cli: openai.AsyncClient,
    session: AsyncSession,
    class_id: int,
    user_id: int,
    after: datetime,
    nowfn: NowFn = utcnow,
) -> None:
    class_ = await models.Class.get_by_id(session, class_id)
    if not class_:
        raise ValueError(f"Class with ID {class_id} not found")

    user = await models.User.get_by_id(session, user_id)
    if not user:
        raise ValueError(f"User with ID {user_id} not found")

    ai_assistant_summaries = await generate_assistant_summaries(
        cli, session, class_.id, after
    )
    if not ai_assistant_summaries:
        return

    class_summary = convert_to_class_summary(
        class_.id, class_.name, ai_assistant_summaries
    )
    summary_html = generate_summary_html_from_assistant_summaries(
        class_summary.assistant_summaries
    )

    magic_link = generate_auth_link(
        user.id,
        expiry=86_400 * 7,
        nowfn=nowfn,
        redirect=f"/group/{class_.id}/manage",
    )

    days_before_today = (nowfn() - after).days

    export_options = ClassSummaryExport(
        class_name=class_.name,
        summary_html=summary_html,
        link=magic_link,
        first_name=user.first_name or user.display_name or "Moderator",
        email=user.email,
        time_since=f"the last {days_before_today} days",
    )

    await send_summary(config.email.sender, export_options)


async def generate_assistant_summaries(
    cli: openai.AsyncClient,
    session: AsyncSession,
    class_id: int,
    after: datetime,
) -> list[AIAssistantSummary] | None:
    summaries = list[AIAssistantSummary]()
    current_period_contains_threads = False

    # Get all assistants for the class
    async for id_, name in models.Assistant.async_get_id_name_by_class_id(
        session=session, class_id=class_id
    ):
        user_messages_list = list[ThreadUserMessages]()
        async for thread in models.Thread.get_threads_by_assistant_id(
            session=session, assistant_id=id_, after=after
        ):
            user_messages_list.append(
                ThreadUserMessages(
                    id=thread.id,
                    thread_id=thread.thread_id,
                    user_messages=await get_thread_user_messages(cli, thread.thread_id),
                )
            )

        if user_messages_list:
            current_period_contains_threads = True
            assistant_summary = await generate_thread_summary(cli, user_messages_list)
            summaries.append(
                AIAssistantSummary(
                    assistant_name=name,
                    questions=assistant_summary.questions if assistant_summary else [],
                )
            )
        else:
            summaries.append(AIAssistantSummary(assistant_name=name, questions=[]))

    if not current_period_contains_threads:
        return None
    return summaries


def convert_thread_id_to_url(thread_id: int, class_id: int) -> str:
    return config.url(f"/group/{class_id}/thread/{thread_id}")


def convert_to_class_summary(
    class_id: int, class_name: str, ai_assistant_summaries: list[AIAssistantSummary]
) -> ClassSummary:
    assistant_summaries = []

    for ai_assistant_summary in ai_assistant_summaries:
        # Convert AIQuestionSummary to QuestionSummary
        questions = []
        for question_summary in ai_assistant_summary.questions:
            relevant_thread_urls = [
                convert_thread_id_to_url(thread_id, class_id)
                for thread_id in question_summary.relevant_threads
            ]
            questions.append(
                QuestionSummary(
                    question=question_summary.question,
                    relevant_thread_urls=relevant_thread_urls,
                )
            )

        # Build AssistantSummary
        assistant_summaries.append(
            AssistantSummary(
                assistant_name=ai_assistant_summary.assistant_name, questions=questions
            )
        )

    # Build and return ClassSummary
    return ClassSummary(
        class_id=class_id,
        class_name=class_name,
        assistant_summaries=assistant_summaries,
    )


async def get_thread_user_messages(
    cli: openai.AsyncClient, thread_id: str, words: int = 100
) -> list[str]:
    messages = await cli.beta.threads.messages.list(thread_id, limit=10, order="asc")

    user_messages = list[str]()
    for message in messages.data:
        for content in message.content:
            if message.role == "user":
                if content.type == "text":
                    user_messages.append(
                        f"{' '.join(content.text.value.split()[:words])}"
                    )
                if content.type in ["image_file", "image_url"]:
                    user_messages.append("User uploaded an image file")
    return user_messages


summarization_prompt = """
Extract key topics from a list of user queries in chatbot threads provided in the specified JSON schema. If there are no valuable topics or threads for an assistant, do not return any results. Ensure that no single thread ID is listed more than once for the same topic.

# Input Format

The user threads will be provided in the following JSON schema:
```json
{
    "threads": [
        {
            "id": 122,
            "user_messages": ["User message 1", "User message 2"]
        },
    ]
}
```

# Steps

1. **Identify Key Topics**: Examine the list of query threads to recognize recurring themes or topics that users discussed.

2. **Gather Thread IDs**: Record the thread IDs of threads that contribute to each significant topic identified.

3. **Organize and Limit**: Structure the findings into a list of thread IDs. Return a maximum of 5 thread IDs per topic.

4. **Check for Results**: Ensure there are threads with valuable topics before returning results. If no such threads or topics exist, return nothing.

# Output Format

The output must be a list of integer thread IDs. If no valuable topics or threads are found, return an empty array.

# Notes

- Ensure each entry in the output accurately reflects the threads associated with the recognized user topics.
- Each list of thread IDs should distinctly capture the source threads of each theme or topic without extraneous detail.
- Adhere to constraints: max 5 thread IDs per recognized topic.
- Ensure that no single thread ID is listed more than once for the same topic.
- Do not output any JSON if there are no valuable topics or threads.
"""


async def generate_thread_summary(
    cli: openai.AsyncClient, thread_messages: list[ThreadUserMessages]
) -> AIAssistantSummaryOutput | None:
    completion = await cli.beta.chat.completions.parse(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": summarization_prompt},
            {
                "role": "user",
                "content": ThreadsToSummarize(threads=thread_messages).model_dump_json(
                    exclude={"threads": {"__all__": {"thread_id"}}}
                ),
            },
        ],
        response_format=AIAssistantSummaryOutput,
        temperature=0.0,
    )

    return completion.choices[0].message.parsed


def generate_summary_html_from_assistant_summaries(
    summaries: list[AssistantSummary],
) -> str:
    summary_html = ""
    for summary in summaries:
        summary_html += f"""
         <div class="summary-container">
            <div class="summary-tab">{summary.assistant_name}</div>
            <div class="summary-box">
         """
        if summary.questions:
            summary_html += """
               <ul>
            """
            for item in summary.questions:
                summary_html += f"""
                <li>{item.question}</li>
                """
                if item.relevant_thread_urls:
                    summary_html += """
                    <div class="link-row">
                        <span class="link-label">Relevant threads:</span>
                    """
                    for i, thread_url in enumerate(item.relevant_thread_urls, start=1):
                        summary_html += f"""
                    <a href="{thread_url}" class="numbered-circle">{i}</a>
                    """
                    summary_html += "</div>"
            summary_html += """
               </ul>
            """
        else:
            summary_html += """
               <p><i>No activity.</i></p>
            """
        summary_html += """
            </div>
         </div>
         """
    return summary_html
