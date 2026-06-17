from io import BytesIO

import pytest

from pingpong.artifacts import ArtifactStoreError, LocalArtifactStore


@pytest.mark.asyncio
async def test_local_artifact_store_delete_removes_file(tmp_path):
    store = LocalArtifactStore(str(tmp_path))

    await store.put("notes.md", BytesIO(b"# Notes"), "text/markdown")
    assert (tmp_path / "notes.md").read_bytes() == b"# Notes"

    await store.delete("notes.md")
    assert not (tmp_path / "notes.md").exists()

    await store.delete("notes.md")


@pytest.mark.asyncio
async def test_local_artifact_store_delete_rejects_path_traversal(tmp_path):
    store = LocalArtifactStore(str(tmp_path / "store"))
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("keep")

    with pytest.raises(ArtifactStoreError) as exc_info:
        await store.delete("../outside.txt")

    assert exc_info.value.code == 400
    assert outside_file.read_text() == "keep"
