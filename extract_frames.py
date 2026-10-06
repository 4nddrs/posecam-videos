#!/usr/bin/env python3
"""Extract frames from MP4 videos stored in Cloudflare R2 and upload them back.

For every ``<YYYY-MM-DD>/<name>.mp4`` in the bucket (ignoring ``frames/``):

1. download the video to a temporary directory,
2. extract frames at a fixed rate with ffmpeg's ``fps`` filter (uniform
   sampling by time, not by frame index),
3. upload them concurrently to ``frames/<YYYY-MM-DD>/<name>/frame_000001.jpg``...,
4. upload ``frames/<YYYY-MM-DD>/<name>/index.json`` last, only after every
   frame was uploaded. Its presence marks the video as done, which makes the
   script idempotent and resumable.

Credentials are read from ``.env`` next to this script and are never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv

REQUIRED_ENV = (
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET_NAME",
)
SECRET_ENV = REQUIRED_ENV + ("R2_PUBLIC_BASE_URL", "R2_ENDPOINT")

FRAMES_ROOT = "frames/"
DEFAULT_FPS = 5
JPEG_QUALITY = 3
FRAME_PATTERN = "frame_%06d.jpg"
PTS_TIME_RE = re.compile(r"\bpts_time:\s*(-?[0-9.]+)")


def redact(text: str) -> str:
    """Remove any .env value from a message before it is printed."""
    for name in SECRET_ENV:
        value = os.environ.get(name)
        if value and len(value) >= 4:
            text = text.replace(value, f"<{name}>")
    return text


def log(message: str) -> None:
    print(redact(message), flush=True)


@dataclass
class Video:
    key: str
    size: int

    @property
    def frames_prefix(self) -> str:
        stem, _ = posixpath.splitext(self.key)
        return f"{FRAMES_ROOT}{stem}/"

    @property
    def index_key(self) -> str:
        return f"{self.frames_prefix}index.json"


@dataclass
class VideoStats:
    key: str
    size_bytes: int
    duration: float = 0.0
    frame_count: int = 0
    download_s: float = 0.0
    extract_s: float = 0.0
    upload_s: float = 0.0
    timings: dict[str, float] = field(default_factory=dict)


def load_config() -> dict[str, str]:
    load_dotenv(Path(__file__).resolve().parent / ".env")
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        sys.exit(f"Missing required variables in .env: {', '.join(missing)}")
    return {name: os.environ[name] for name in REQUIRED_ENV}


def make_client(config: dict[str, str], workers: int):
    return boto3.client(
        "s3",
        endpoint_url=f"https://{config['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=config["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=config["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(
            max_pool_connections=workers + 4,
            retries={"max_attempts": 10, "mode": "adaptive"},
        ),
    )


def list_videos(s3, bucket: str) -> list[Video]:
    videos = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.startswith(FRAMES_ROOT) or not key.lower().endswith(".mp4"):
                continue
            videos.append(Video(key=key, size=obj["Size"]))
    videos.sort(key=lambda v: v.key)
    return videos


def object_exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def probe(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "format=duration,start_time:stream=r_frame_rate,avg_frame_rate,nb_frames",
            "-of", "json", str(path),
        ],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


def extract_frames(video_path: Path, out_dir: Path, fps: int) -> list[float]:
    """Run ffmpeg and return the presentation timestamp of every written frame.

    ``showinfo`` after ``fps`` logs the pts_time of each output frame, and
    ``-vsync passthrough`` keeps a 1:1 mapping between those frames and files.
    """
    result = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "info",
            "-i", str(video_path),
            "-vf", f"fps={fps},showinfo",
            "-vsync", "passthrough",
            "-q:v", str(JPEG_QUALITY),
            str(out_dir / FRAME_PATTERN),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-10:])
        raise RuntimeError(f"ffmpeg failed ({result.returncode}):\n{tail}")
    return [
        float(match.group(1))
        for line in result.stderr.splitlines()
        if "Parsed_showinfo" in line and (match := PTS_TIME_RE.search(line))
    ]


def upload_frames(s3, bucket: str, frames: list[Path], prefix: str, workers: int) -> None:
    def upload(path: Path) -> None:
        s3.upload_file(
            str(path), bucket, prefix + path.name,
            ExtraArgs={"ContentType": "image/jpeg"},
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(upload, frame) for frame in frames]
        for future in as_completed(futures):
            future.result()


def process_video(s3, bucket: str, video: Video, fps: int, workers: int, tmp_root: str | None) -> VideoStats:
    stats = VideoStats(key=video.key, size_bytes=video.size)
    with tempfile.TemporaryDirectory(prefix="scriptframe-", dir=tmp_root) as tmp:
        tmp_dir = Path(tmp)
        video_path = tmp_dir / "video.mp4"
        frames_dir = tmp_dir / "frames"
        frames_dir.mkdir()

        start = time.perf_counter()
        s3.download_file(bucket, video.key, str(video_path))
        stats.download_s = time.perf_counter() - start

        info = probe(video_path)
        stats.duration = float(info["format"]["duration"])
        start_time = float(info["format"].get("start_time", 0.0))

        start = time.perf_counter()
        timestamps = extract_frames(video_path, frames_dir, fps)
        stats.extract_s = time.perf_counter() - start

        frames = sorted(frames_dir.glob("frame_*.jpg"))
        if not frames:
            raise RuntimeError("ffmpeg produced no frames")
        if len(timestamps) != len(frames):
            log(f"  warning: {len(timestamps)} timestamps for {len(frames)} frames; using index/fps")
            timestamps = [start_time + i / fps for i in range(len(frames))]
        stats.frame_count = len(frames)

        start = time.perf_counter()
        upload_frames(s3, bucket, frames, video.frames_prefix, workers)
        index = {
            "video_key": video.key,
            "fps": fps,
            "frame_count": len(frames),
            "duration": stats.duration,
            "start_time": start_time,
            "frames": [
                {"key": video.frames_prefix + frame.name, "timestamp": round(ts, 6)}
                for frame, ts in zip(frames, timestamps)
            ],
        }
        # index.json goes last: it is the completion marker for resumability.
        s3.put_object(
            Bucket=bucket, Key=video.index_key,
            Body=json.dumps(index, indent=2).encode(),
            ContentType="application/json",
        )
        stats.upload_s = time.perf_counter() - start
    return stats


def format_seconds(seconds: float) -> str:
    minutes, secs = divmod(int(round(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m{secs:02d}s" if hours else f"{minutes}m{secs:02d}s"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, help="process at most N pending videos")
    parser.add_argument("--dry-run", action="store_true", help="only list what would be done")
    parser.add_argument("--workers", type=int, default=24, help="concurrent uploads (default: 24)")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS, help=f"frames per second (default: {DEFAULT_FPS})")
    parser.add_argument("--tmp-dir", help="parent directory for temporary files")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()
    bucket = config["R2_BUCKET_NAME"]
    s3 = make_client(config, args.workers)

    videos = list_videos(s3, bucket)
    total_gb = sum(v.size for v in videos) / 1e9
    log(f"Found {len(videos)} videos ({total_gb:.2f} GB)")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        done = list(pool.map(lambda v: object_exists(s3, bucket, v.index_key), videos))
    pending = [video for video, is_done in zip(videos, done) if not is_done]
    log(f"{len(videos) - len(pending)} video(s) already done (index.json present), skipping")
    if args.limit is not None:
        pending = pending[: args.limit]
    log(f"{len(pending)} video(s) to process")

    if args.dry_run:
        for video in pending:
            log(f"would process {video.key} ({video.size / 1e6:.1f} MB) -> {video.frames_prefix}")
        return 0

    all_stats: list[VideoStats] = []
    failures = 0
    for n, video in enumerate(pending, 1):
        log(f"[{n}/{len(pending)}] {video.key} ({video.size / 1e6:.1f} MB)")
        try:
            stats = process_video(s3, bucket, video, args.fps, args.workers, args.tmp_dir)
        except Exception as exc:  # keep going; the video stays pending for the next run
            failures += 1
            log(f"  FAILED: {exc}")
            continue
        all_stats.append(stats)
        log(
            f"  duration {stats.duration:.1f}s | frames {stats.frame_count} | "
            f"download {stats.download_s:.1f}s | extract {stats.extract_s:.1f}s | "
            f"upload {stats.upload_s:.1f}s"
        )

    if all_stats:
        log(
            "Totals: "
            f"download {format_seconds(sum(s.download_s for s in all_stats))}, "
            f"extract {format_seconds(sum(s.extract_s for s in all_stats))}, "
            f"upload {format_seconds(sum(s.upload_s for s in all_stats))}, "
            f"{sum(s.frame_count for s in all_stats)} frames"
        )
    log(f"Done: {len(all_stats)} ok, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        log(f"Error: {type(exc).__name__}: {exc}")
        sys.exit(1)
