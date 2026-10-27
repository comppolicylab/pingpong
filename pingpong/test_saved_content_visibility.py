import importlib
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from pingpong import models, schemas
from pingpong.ai import build_response_input_item_list, list_export_rows_v3
from pingpong.testutil import with_authz, with_user


@pytest.fixture
async def saved_content(db):
    async with db.async_session() as session:
        session.add(models.Class(id=1, name="Class", api_key="test-key"))
        session.add(
            models.Assistant(
                id=2, class_id=1, name="Assistant", version=3, model="gpt-4o-mini"
            )
        )
        session.add(
            models.Thread(
                id=20,
                class_id=1,
                assistant_id=2,
                version=3,
                name="Chat",
                private=False,
                tools_available="[]",
            )
        )
        await session.flush()
        records = {}
        for index, release_status in enumerate(schemas.RunReleaseStatus):
            label = release_status.value
            run = models.Run(
                thread_id=20,
                assistant_id=2,
                status=schemas.RunStatus.COMPLETED,
                release_status=release_status,
            )
            session.add(run)
            await session.flush()
            messages = []
            for offset, role in enumerate(
                (schemas.MessageRole.USER, schemas.MessageRole.ASSISTANT)
            ):
                message = models.Message(
                    run_id=run.id,
                    thread_id=20,
                    assistant_id=2,
                    role=role,
                    output_index=index * 10 + offset,
                    message_status=schemas.MessageStatus.COMPLETED,
                    content=[
                        models.MessagePart(
                            part_index=0,
                            type=(
                                schemas.MessagePartType.INPUT_TEXT
                                if role == schemas.MessageRole.USER
                                else schemas.MessagePartType.OUTPUT_TEXT
                            ),
                            text=f"{label}_{role.value}_content",
                        )
                    ],
                )
                session.add(message)
                messages.append(message)
            tool = models.ToolCall(
                run_id=run.id,
                thread_id=20,
                output_index=index * 10 + 2,
                tool_call_id=f"tool_{label}",
                type=schemas.ToolCallType.CODE_INTERPRETER,
                status=schemas.ToolCallStatus.COMPLETED,
                code=f"{label}_tool_content",
            )
            reasoning = models.ReasoningStep(
                run_id=run.id,
                thread_id=20,
                output_index=index * 10 + 3,
                reasoning_id=f"reasoning_{label}",
                status=schemas.ReasoningStatus.COMPLETED,
                encrypted_content=f"{label}_encrypted_content",
                summary_parts=[
                    models.ReasoningSummaryPart(
                        part_index=0, summary_text=f"{label}_reasoning_content"
                    )
                ],
            )
            session.add_all([tool, reasoning])
            await session.flush()
            records[label] = {
                "run": run.id,
                "user": messages[0].id,
                "assistant": messages[1].id,
                "tool": tool.id,
                "reasoning": reasoning.id,
            }
        # Prompt inputs must still reach the current run while its gate is closed.
        session.add(
            models.Message(
                run_id=records["pending"]["run"],
                thread_id=20,
                output_index=30,
                role=schemas.MessageRole.DEVELOPER,
                message_status=schemas.MessageStatus.COMPLETED,
                content=[
                    models.MessagePart(
                        part_index=0,
                        type=schemas.MessagePartType.INPUT_TEXT,
                        text="current_prompt_instructions",
                    )
                ],
            )
        )
        await session.commit()
    return records


def assert_visible_text(text):
    for label in ("pending", "withheld", "released"):
        assert f"{label}_user_content" in text
    assert "released_assistant_content" in text
    for label in ("pending", "withheld"):
        for kind in ("assistant", "tool", "reasoning", "encrypted"):
            assert f"{label}_{kind}_content" not in text


@pytest.mark.asyncio
async def test_saved_history_queries_and_direct_lookup(db, saved_content):
    records = saved_content
    async with db.async_session() as session:
        expected_messages = {row["user"] for row in records.values()} | {
            records["released"]["assistant"]
        }
        all_messages = [
            m async for m in models.Thread.list_all_messages_gen(session, 20)
        ]
        assert {
            m.id for m in all_messages if m.role != schemas.MessageRole.DEVELOPER
        } == expected_messages
        by_thread = [
            m async for m in models.Message.get_messages_by_thread_id(session, 20)
        ]
        assert {m.id for m in by_thread} == {m.id for m in all_messages}
        listed = await models.Thread.list_messages(session, 20, limit=1, order="desc")
        assert listed[0].role == schemas.MessageRole.DEVELOPER
        # Filtering happens before LIMIT, so a withheld assistant doesn't consume it.
        listed = await models.Thread.list_messages(
            session, 20, limit=1, before=listed[0].id
        )
        assert listed[0].id == records["withheld"]["user"]
        for include_hidden in (False, True):
            messages, tools, reasoning = await models.Thread.list_messages_tool_calls(
                session,
                20,
                [r["run"] for r in records.values()],
                include_hidden_messages=include_hidden,
            )
            assert {
                m.id for m in messages if m.role != schemas.MessageRole.DEVELOPER
            } == expected_messages
            assert [t.id for t in tools] == [records["released"]["tool"]]
            assert [r.id for r in reasoning] == [records["released"]["reasoning"]]
        for label in ("pending", "withheld"):
            assert (
                await models.Message.get_by_id_with_annotations(
                    session, records[label]["assistant"]
                )
                is None
            )
            assert (
                await models.Message.get_by_id_with_annotations(
                    session, records[label]["user"]
                )
                is not None
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("user_assistant_only", [False, True])
async def test_model_context_excludes_unreleased_output(
    db, saved_content, user_assistant_only
):
    async with db.async_session() as session:
        items = await build_response_input_item_list(
            session,
            thread_id=20,
            current_run_id=saved_content["pending"]["run"],
            uses_reasoning=True,
            user_assistant_messages_only=user_assistant_only,
        )
    text = json.dumps(items, default=str)
    assert_visible_text(text)
    assert "current_prompt_instructions" in text


@pytest.mark.asyncio
async def test_exports_and_detailed_view_exclude_unreleased_output(db, saved_content):
    async with db.async_session() as session:
        rows = await list_export_rows_v3(session, 20, {})
        assert_visible_text(str(rows))
        assert "released_tool_content" in str(rows)
        assert "released_reasoning_content" in str(rows)
        # Previously loaded raw relationships must not bypass the filtered loader.
        await session.scalar(
            select(models.Thread)
            .where(models.Thread.id == 20)
            .options(
                selectinload(models.Thread.runs).selectinload(models.Run.messages),
                selectinload(models.Thread.runs).selectinload(models.Run.tool_calls),
                selectinload(models.Thread.runs).selectinload(
                    models.Run.reasoning_steps
                ),
            )
        )
        thread = await models.Thread.get_by_id_extended_details(session, 20)
        for run in thread.runs:
            if run.release_status != schemas.RunReleaseStatus.RELEASED:
                assert all(
                    m.role != schemas.MessageRole.ASSISTANT for m in run.messages
                )
                assert run.tool_calls == []
                assert run.reasoning_steps == []


@pytest.mark.asyncio
async def test_release_transition_exposes_saved_generated_content(db, saved_content):
    async with db.async_session() as session:
        await session.execute(
            update(models.Run)
            .where(models.Run.id == saved_content["pending"]["run"])
            .values(release_status=schemas.RunReleaseStatus.RELEASED)
        )
        await session.commit()
    async with db.async_session() as session:
        rows = str(await list_export_rows_v3(session, 20, {}))
        assert "pending_assistant_content" in rows
        assert "pending_tool_content" in rows
        assert "pending_reasoning_content" in rows
        assert "withheld_assistant_content" not in rows


@with_user(123)
@with_authz(
    grants=[
        ("user:123", "can_view", "thread:20"),
        ("anonymous_user:shared-session", "can_view", "thread:20"),
    ]
)
@pytest.mark.parametrize("path", ["", "/messages?limit=100"])
@pytest.mark.parametrize("shared", [False, True])
async def test_history_api_excludes_unreleased_output(
    api, db, valid_user_token, monkeypatch, saved_content, path, shared
):
    server = importlib.import_module("pingpong.server")
    if shared:
        async with db.async_session() as session:
            link = await models.AnonymousLink.create(
                session, share_token="shared-link", assistant_id=2
            )
            user = await models.User.create_anonymous_user(
                session, anonymous_link_id=link.id
            )
            await models.AnonymousSession.create(
                session, "shared-session", user_id=user.id
            )
            await session.commit()
    monkeypatch.setitem(
        server.v1.dependency_overrides,
        server.get_openai_client_for_class,
        lambda: SimpleNamespace(),
    )
    headers = (
        {"X-Anonymous-Thread-Session": "shared-session"}
        if shared
        else {"Authorization": f"Bearer {valid_user_token}"}
    )
    response = api.get(f"/api/v1/class/1/thread/20{path}", headers=headers)
    assert response.status_code == 200, response.text
    assert_visible_text(response.text)


@with_user(123)
@with_authz(grants=[("user:123", "admin", "class:1")])
async def test_detailed_api_excludes_unreleased_output(
    api, valid_user_token, saved_content
):
    response = api.get(
        "/api/v1/class/1/thread/20/details",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200, response.text
    assert_visible_text(response.text)


@with_user(123)
@with_authz(grants=[("user:123", "can_view", "thread:20")])
async def test_generated_image_and_file_downloads_obey_release(
    api, db, valid_user_token, monkeypatch, saved_content
):
    server = importlib.import_module("pingpong.server")
    async with db.async_session() as session:
        for label, records in saved_content.items():
            file = models.File(
                class_id=1,
                file_id=f"image-{label}",
                name="chart.png",
                content_type="image/png",
                s3_file=models.S3File(key=f"generated/{label}.png"),
            )
            session.add(file)
            await session.flush()
            # Add the generated reference directly; read APIs deliberately hide it.
            assistant = await session.scalar(
                select(models.Message)
                .where(models.Message.id == records["assistant"])
                .options(selectinload(models.Message.content))
            )
            session.add(
                models.Annotation(
                    message_part_id=assistant.content[0].id,
                    annotation_index=0,
                    type=schemas.AnnotationType.CONTAINER_FILE_CITATION,
                    file_object_id=file.id,
                )
            )
            await session.execute(
                models.image_file_thread_association.insert().values(
                    thread_id=20, file_id=file.id
                )
            )
            records["file"] = file.id
        await session.commit()
    async with db.async_session() as session:
        thread = await models.Thread.get_by_id_extended_details(session, 20)
        assert [file.id for file in thread.image_files] == [
            saved_content["released"]["file"]
        ]
    monkeypatch.setattr(
        server.config,
        "file_store",
        SimpleNamespace(store=SimpleNamespace(get=lambda name: iter([b"image-bytes"]))),
    )
    monkeypatch.setitem(
        server.v1.dependency_overrides,
        server.get_openai_client_for_class,
        lambda: SimpleNamespace(),
    )
    headers = {"Authorization": f"Bearer {valid_user_token}"}
    for label, records in saved_content.items():
        for path in (
            f"image/image-{label}",
            f"message/{records['assistant']}/file/{records['file']}",
        ):
            response = api.get(f"/api/v1/class/1/thread/20/{path}", headers=headers)
            assert response.status_code == (200 if label == "released" else 404), (
                response.text
            )
    # An input-image reference keeps the same file accessible despite a withheld output reference.
    async with db.async_session() as session:
        message = await models.Message.get_by_id_with_annotations(
            session, saved_content["withheld"]["user"]
        )
        session.add(
            models.MessagePart(
                message_id=message.id,
                part_index=1,
                type=schemas.MessagePartType.INPUT_IMAGE,
                input_image_file_object_id=saved_content["withheld"]["file"],
            )
        )
        await session.commit()
    response = api.get(
        "/api/v1/class/1/thread/20/image/image-withheld", headers=headers
    )
    assert response.status_code == 200
