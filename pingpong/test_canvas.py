from unittest.mock import AsyncMock

import pytest

from pingpong.canvas import CanvasCourseClient, CanvasException


class StubCanvasCourseClient(CanvasCourseClient):
    def _sync_allowed(self, last_synced, now):
        pass

    async def _update_user_roles(self):
        pass

    def _raise_sync_error_if_manual(self):
        pass


@pytest.mark.asyncio
async def test_roster_access_check_rejects_course_id_path_injection():
    client = object.__new__(StubCanvasCourseClient)
    client._request_all_pages = AsyncMock()

    with pytest.raises(CanvasException) as exc_info:
        await client._roster_access_check("../accounts/1")

    assert exc_info.value.code == 400
    assert exc_info.value.detail == "Invalid Canvas course ID"
    client._request_all_pages.assert_not_called()


@pytest.mark.asyncio
async def test_roster_access_check_preserves_numeric_course_ids():
    client = object.__new__(StubCanvasCourseClient)
    requested_paths = []

    async def request_all_pages(path, **kwargs):
        requested_paths.append((path, kwargs))
        yield []

    client._request_all_pages = request_all_pages

    assert await client._roster_access_check("123") is False
    assert requested_paths == [
        ("/api/v1/courses/123/users", {"params": {"include[]": ["enrollments"]}})
    ]
