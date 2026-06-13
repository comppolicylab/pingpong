import pytest

from pingpong.audio_store import AudioStoreError, LocalAudioStore

pytestmark = pytest.mark.asyncio


async def _collect(gen) -> bytes:
    out = bytearray()
    async for chunk in gen:
        out.extend(chunk)
    return bytes(out)


async def _write(store: LocalAudioStore, key: str, data: bytes) -> None:
    upload = await store.create_upload(name=key, content_type="audio/webm")
    import io

    await upload.upload_part(io.BytesIO(data))
    await upload.complete_upload()


async def test_stream_file_range_returns_requested_slice(tmp_path):
    store = LocalAudioStore(str(tmp_path))
    payload = bytes(range(256)) * 10  # 2560 bytes
    await _write(store, "audio.webm", payload)

    # Open-ended range (the shape a browser sends when it seeks): bytes=N-
    assert (
        await _collect(store.stream_file_range("audio.webm", start=1000, end=None))
        == payload[1000:]
    )
    # Bounded range: bytes=N-M (end is inclusive, matching HTTP semantics)
    assert (
        await _collect(store.stream_file_range("audio.webm", start=1000, end=1099))
        == payload[1000:1100]
    )
    # No range => whole file
    assert await _collect(store.stream_file_range("audio.webm")) == payload
    # get_file remains equivalent to a full-range read
    assert await _collect(store.get_file("audio.webm")) == payload


async def test_stream_file_range_rejects_unsatisfiable_ranges(tmp_path):
    store = LocalAudioStore(str(tmp_path))
    await _write(store, "audio.webm", b"0123456789")

    with pytest.raises(AudioStoreError) as start_oob:
        await _collect(store.stream_file_range("audio.webm", start=10, end=None))
    assert start_oob.value.code == 416

    with pytest.raises(AudioStoreError) as end_before_start:
        await _collect(store.stream_file_range("audio.webm", start=5, end=2))
    assert end_before_start.value.code == 416

    with pytest.raises(AudioStoreError) as missing:
        await _collect(store.stream_file_range("missing.webm", start=0, end=None))
    assert missing.value.code == 404
