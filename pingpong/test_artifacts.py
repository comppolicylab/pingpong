from io import BytesIO

import pytest

from pingpong.artifacts import LocalArtifactStore


@pytest.mark.asyncio
async def test_local_artifact_store_delete_removes_file(tmp_path):
    store = LocalArtifactStore(str(tmp_path))

    await store.put("notes.md", BytesIO(b"# Notes"), "text/markdown")
    assert (tmp_path / "notes.md").read_bytes() == b"# Notes"

    await store.delete("notes.md")
    assert not (tmp_path / "notes.md").exists()

    await store.delete("notes.md")
