"""
Standalone video streaming test - no dependencies on the main PingPong app.

Usage:
    python test_video_streaming.py

Then open: http://localhost:8001/
"""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pathlib import Path
import re
from pingpong.video_stream import VideoStreamError

# Config (s3 or local)
# Set to "s3" if attempting to stream a video from s3! otherwise should be set to the Local Video folder
VIDEO_DIR = "s3"
# Uncomment the line below if running locally
# video_stream = LocalVideoStream(VIDEO_DIR)
# For S3 testing (uncomment and configure):
from pingpong.video_stream import S3VideoStream

S3_BUCKET = "--insert-bucket-here--"
video_stream = S3VideoStream(S3_BUCKET, authenticated=False)
TEST_VIDEO_KEY = "--insert-key-here--"
app = FastAPI(title="video stream test")
# ======================================


def parse_range_header(range_header: str, file_size: int) -> tuple[int, int]:
    """Parse HTTP Range header and return (start, end) byte positions."""
    match = re.match(r"bytes=(\d*)-(\d*)", range_header)
    if not match:
        return 0, file_size - 1

    start_str, end_str = match.groups()
    start = int(start_str) if start_str else 0
    end = int(end_str) if end_str else file_size - 1

    return start, min(end, file_size - 1)


@app.get("/video/{video_key:path}")
async def stream_video(video_key: str, request: Request):
    """Stream a video file with HTTP range request support for seeking."""
    try:
        metadata = await video_stream.get_metadata(video_key)
        range_header = request.headers.get("range")

        if range_header:
            # Handle range request (for video seeking)
            start, end = parse_range_header(range_header, metadata.content_length)
            content_length = end - start + 1

            headers = {
                "Content-Range": f"bytes {start}-{end}/{metadata.content_length}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(content_length),
                "Content-Type": metadata.content_type,
            }

            if metadata.etag:
                headers["ETag"] = metadata.etag
            if metadata.last_modified:
                headers["Last-Modified"] = str(metadata.last_modified)

            return StreamingResponse(
                video_stream.stream_video_range(video_key, start, end),
                status_code=206,
                headers=headers,
                media_type=metadata.content_type,
            )
        else:
            # Handle full file request
            headers = {
                "Accept-Ranges": "bytes",
                "Content-Length": str(metadata.content_length),
                "Content-Type": metadata.content_type,
            }

            if metadata.etag:
                headers["ETag"] = metadata.etag
            if metadata.last_modified:
                headers["Last-Modified"] = str(metadata.last_modified)

            return StreamingResponse(
                video_stream.stream_video(video_key),
                headers=headers,
                media_type=metadata.content_type,
            )

    except VideoStreamError as e:
        from fastapi import HTTPException

        raise HTTPException(status_code=e.code or 500, detail=e.detail)
    except Exception as e:
        from fastapi import HTTPException

        raise HTTPException(status_code=500, detail=f"Error streaming video: {str(e)}")


@app.get("/", response_class=HTMLResponse)
async def test_page():
    """Serve a test HTML page with video player."""
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Video Stream Test</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                max-width: 1200px;
                margin: 50px auto;
                padding: 20px;
                background: #f5f5f5;
            }}
            .container {{
                background: white;
                padding: 30px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            h1 {{
                color: #333;
                margin-bottom: 20px;
            }}
            video {{
                width: 100%;
                max-width: 1200px;
                min-height: 500px;
                background: #000;
                border-radius: 4px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            }}
            .info {{
                margin-top: 20px;
                padding: 15px;
                background: #f0f0f0;
                border-radius: 4px;
            }}
            .status {{
                margin-top: 10px;
                padding: 10px;
                background: #e3f2fd;
                border-left: 4px solid #2196f3;
                border-radius: 4px;
            }}
            .error {{
                background: #ffebee;
                border-left-color: #f44336;
            }}
            .success {{
                background: #e8f5e9;
                border-left-color: #4caf50;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎥 Video Stream Test</h1>

            <video id="videoPlayer" controls>
                <source src="/video/{TEST_VIDEO_KEY}" type="video/mp4">
                Your browser does not support the video tag.
            </video>

            <div class="info">
                <h3>Test Information</h3>
                <p><strong>Video URL:</strong> <code>/video/{TEST_VIDEO_KEY}</code></p>
                <p><strong>Storage:</strong> {video_stream.__class__.__name__}</p>
                <p><strong>Location:</strong> <code>{getattr(video_stream, "_directory", "N/A")}</code></p>
            </div>

            <div id="status" class="status">
                <strong>Status:</strong> <span id="statusText">Loading...</span>
            </div>

            <div class="info" style="margin-top: 20px;">
                <h3>Testing Checklist</h3>
                <ul>
                    <li>✅ Video loads and plays</li>
                    <li>✅ Seeking works (drag progress bar)</li>
                    <li>✅ Pause/Resume works</li>
                    <li>✅ Volume controls work</li>
                    <li>✅ Fullscreen works</li>
                </ul>
            </div>
        </div>

        <script>
            const video = document.getElementById('videoPlayer');
            const status = document.getElementById('status');
            const statusText = document.getElementById('statusText');

            video.addEventListener('loadstart', () => {{
                statusText.textContent = 'Loading video...';
                status.className = 'status';
            }});

            video.addEventListener('loadedmetadata', () => {{
                const duration = Math.floor(video.duration);
                const minutes = Math.floor(duration / 60);
                const seconds = duration % 60;
                statusText.textContent = `Video loaded! Duration: ${{minutes}}:${{seconds.toString().padStart(2, '0')}}`;
                status.className = 'status success';
            }});

            video.addEventListener('error', (e) => {{
                statusText.textContent = `Error: ${{video.error?.message || 'Unknown error'}}`;
                status.className = 'status error';
                console.error('Video error:', video.error);
            }});

            video.addEventListener('play', () => {{
                statusText.textContent = 'Playing...';
                status.className = 'status success';
            }});

            video.addEventListener('pause', () => {{
                statusText.textContent = 'Paused';
                status.className = 'status';
            }});

            video.addEventListener('seeking', () => {{
                statusText.textContent = 'Seeking...';
                status.className = 'status';
            }});

            video.addEventListener('seeked', () => {{
                statusText.textContent = 'Seek complete - Range requests working!';
                status.className = 'status success';
            }});

            console.log('Video source:', video.src);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@app.get("/api/video-info/{video_key:path}")
async def get_video_info(video_key: str):
    """Get metadata about a video file. Locally tested"""
    try:
        metadata = await video_stream.get_metadata(video_key)
        return {
            "content_length": metadata.content_length,
            "content_type": metadata.content_type,
            "etag": metadata.etag,
            "last_modified": metadata.last_modified,
            "size_mb": round(metadata.content_length / (1024 * 1024), 2),
        }
    except VideoStreamError as e:
        from fastapi import HTTPException

        raise HTTPException(status_code=e.code or 500, detail=e.detail)


if __name__ == "__main__":
    import uvicorn

    print("=" * 60)
    print("Video Stream Test")
    print("=" * 60)
    print(f"\n Using Video directory: {Path(VIDEO_DIR).absolute()}")
    print(f"Test video: {TEST_VIDEO_KEY}")
    print("\nOpen browser to: http://localhost:8001/")
    print("\nStarting...\n")

    uvicorn.run(app, host="0.0.0.0", port=8001)
