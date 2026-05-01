import asyncio
import io
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

import uuid_utils as uuid
from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.models as models
from pingpong.config import config
from pingpong.video_store import VideoInputSource, VideoStoreError

logger = logging.getLogger(__name__)

_POSTER_TARGET_OFFSET_FRACTION = 0.05
_POSTER_MIN_OFFSET_MS = 1_000
_POSTER_MAX_OFFSET_MS = 30_000
_POSTER_FALLBACK_OFFSET_MS = 2_000
_POSTER_MAX_WIDTH = 1_280
_POSTER_QUALITY = 80
_POSTER_CONTENT_TYPE = "image/webp"
_POSTER_FFMPEG_TIMEOUT_SECONDS = 60
_POSTER_FFPROBE_TIMEOUT_SECONDS = 30


def _generate_poster_store_key() -> str:
    return f"lv_poster_{uuid.uuid7()}.webp"


def _compute_poster_offset_ms(duration_ms: int | None) -> int:
    if duration_ms is None or duration_ms <= 0:
        return _POSTER_FALLBACK_OFFSET_MS
    raw_offset = int(duration_ms * _POSTER_TARGET_OFFSET_FRACTION)
    clamped = max(_POSTER_MIN_OFFSET_MS, min(_POSTER_MAX_OFFSET_MS, raw_offset))
    # Never seek past the end of a very short video.
    if clamped >= duration_ms:
        return max(0, duration_ms // 2)
    return clamped


async def _probe_duration_ms(video_source: VideoInputSource) -> int | None:
    def run_ffprobe() -> int | None:
        ffprobe_path = shutil.which("ffprobe")
        if ffprobe_path is None:
            return None
        try:
            result = subprocess.run(
                [
                    ffprobe_path,
                    "-v",
                    "quiet",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "csv=p=0",
                    video_source.url,
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=_POSTER_FFPROBE_TIMEOUT_SECONDS,
            )
            seconds = float(result.stdout.strip())
            return int(seconds * 1000)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
            return None

    return await asyncio.to_thread(run_ffprobe)


async def _extract_poster_to_path(
    video_source: VideoInputSource,
    output_path: Path,
    offset_ms: int,
) -> bool:
    try:
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{offset_ms / 1000:.3f}",
            *video_source.ffmpeg_input_args,
            "-i",
            video_source.url,
            "-frames:v",
            "1",
            "-vf",
            f"scale='min({_POSTER_MAX_WIDTH},iw)':-2",
            "-c:v",
            "libwebp",
            "-quality",
            str(_POSTER_QUALITY),
            str(output_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        logger.warning(
            "ffmpeg is unavailable; skipping lecture video poster extraction"
        )
        return False

    try:
        _, stderr = await asyncio.wait_for(
            process.communicate(), timeout=_POSTER_FFMPEG_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        process.kill()
        _, stderr = await process.communicate()
        logger.warning(
            "Timed out extracting lecture video poster. offset_ms=%s stderr=%s",
            offset_ms,
            stderr.decode("utf-8", errors="ignore").strip(),
        )
        return False

    if process.returncode != 0 or not output_path.exists():
        logger.warning(
            "Failed to extract lecture video poster. offset_ms=%s stderr=%s",
            offset_ms,
            stderr.decode("utf-8", errors="ignore").strip(),
        )
        return False
    return True


async def _video_source_for_lecture_video(
    lecture_video: models.LectureVideo,
) -> VideoInputSource | None:
    if not config.video_store or lecture_video.stored_object is None:
        return None
    try:
        return await config.video_store.store.get_ffmpeg_input_source(
            lecture_video.stored_object.key
        )
    except VideoStoreError as e:
        logger.warning(
            "Unable to open lecture video for poster extraction. lecture_video_id=%s error=%s",
            lecture_video.id,
            e.detail or str(e),
        )
        return None


async def extract_poster_bytes(
    *,
    video_source: VideoInputSource | None = None,
    local_video_path: str | None = None,
) -> bytes | None:
    """Extract a single WEBP poster frame.

    Pass `local_video_path` when the video is already on disk (e.g. inside the
    manifest pipeline) for a fast probe + extract. Otherwise pass a
    `video_source` from the configured video store.
    """
    if local_video_path is not None:
        source = VideoInputSource(
            url=Path(local_video_path).as_uri(),
            ffmpeg_input_args=[],
        )
    elif video_source is not None:
        source = video_source
    else:
        return None

    duration_ms = await _probe_duration_ms(source)
    offset_ms = _compute_poster_offset_ms(duration_ms)

    with tempfile.TemporaryDirectory(prefix="pingpong_lv_poster_") as tmp_dir:
        output_path = Path(tmp_dir) / "poster.webp"
        ok = await _extract_poster_to_path(source, output_path, offset_ms)
        if not ok:
            return None
        try:
            return output_path.read_bytes()
        except OSError:
            logger.exception(
                "Failed to read extracted poster file. offset_ms=%s", offset_ms
            )
            return None


async def _persist_poster_bytes(
    session: AsyncSession,
    lecture_video: models.LectureVideo,
    poster_bytes: bytes,
) -> models.LectureVideoPosterStoredObject | None:
    if not config.video_store:
        return None

    store_key = _generate_poster_store_key()

    try:
        await config.video_store.store.put(
            store_key, io.BytesIO(poster_bytes), _POSTER_CONTENT_TYPE
        )
    except VideoStoreError as e:
        logger.warning(
            "Failed to upload lecture video poster. lecture_video_id=%s error=%s",
            lecture_video.id,
            e.detail or str(e),
        )
        return None
    except Exception:
        logger.exception(
            "Unexpected error uploading lecture video poster. lecture_video_id=%s",
            lecture_video.id,
        )
        return None

    try:
        stored_object = await models.LectureVideoPosterStoredObject.create(
            session,
            key=store_key,
            content_type=_POSTER_CONTENT_TYPE,
        )
        lecture_video.poster_stored_object_id = stored_object.id
        lecture_video.poster_stored_object = stored_object
        await session.flush()
        return stored_object
    except Exception:
        logger.exception(
            "Failed to persist lecture video poster row. lecture_video_id=%s key=%s",
            lecture_video.id,
            store_key,
        )
        try:
            await config.video_store.store.delete(store_key)
        except Exception:
            logger.exception(
                "Failed to clean up uploaded poster after DB error. key=%s",
                store_key,
            )
        return None


async def extract_and_store_poster(
    session: AsyncSession,
    lecture_video: models.LectureVideo,
    *,
    local_video_path: str | None = None,
) -> models.LectureVideoPosterStoredObject | None:
    if lecture_video.poster_stored_object_id is not None:
        return None

    if local_video_path is not None:
        poster_bytes = await extract_poster_bytes(local_video_path=local_video_path)
    else:
        video_source = await _video_source_for_lecture_video(lecture_video)
        if video_source is None:
            return None
        poster_bytes = await extract_poster_bytes(video_source=video_source)

    if poster_bytes is None:
        return None

    return await _persist_poster_bytes(session, lecture_video, poster_bytes)
