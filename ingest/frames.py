"""Extract frames from the MP4 videos stored in R2 and upload them back.

Usage: python -m ingest.frames [--limit N] [--dry-run] [--workers N]
                               [--fps N] [--tmp-dir DIR]

For every ``<day>/<name>.mp4`` in the bucket (ignoring ``frames/``), it
downloads the video, extracts frames at a fixed rate, uploads them to
``frames/<day>/<name>/frame_000001.jpg``... and finally uploads
``frames/<day>/<name>/index.json``. The index is written last, only after
every frame was uploaded: its presence marks the video as done, which makes
the step idempotent and resumable. MAX_FRAME_VIDEOS_PER_RUN caps the videos
handled per run (``--limit`` overrides it).
"""
from __future__ import annotations

import argparse
import json
import os
import posixpath
import sys
import tempfile
import time
from collections.abc import Mapping, MutableMapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ingest.adapters.frames import FfmpegFrameExtractor
from ingest.main import load_dotenv_file
from ingest.ports import FrameExtractor

FRAMES_ROOT = "frames/"
DEFAULT_FPS = 5
DEFAULT_WORKERS = 24
MISSING_CODES = ("404", "NoSuchKey", "NotFound")
R2_REQUIRED = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")
SECRET_ENV = R2_REQUIRED + ("R2_BUCKET_NAME", "R2_PUBLIC_BASE_URL", "R2_ENDPOINT")


@dataclass(frozen=True)
class Video:
    key: str
    size: int


@dataclass
class FramesReport:
    processed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    deferred: list[str] = field(default_factory=list)


def redact(text: str, env: Mapping[str, str] | None = None) -> str:
    """Remove any credential value from a message before it is printed."""
    env = os.environ if env is None else env
    for name in SECRET_ENV:
        value = env.get(name)
        if value and len(value) >= 4:
            text = text.replace(value, f"<{name}>")
    return text


def _default_log(message: str) -> None:
    print(redact(message), flush=True)


def frames_prefix(video_key: str) -> str:
    stem, _ = posixpath.splitext(video_key)
    return f"{FRAMES_ROOT}{stem}/"


def index_key(video_key: str) -> str:
    return f"{frames_prefix(video_key)}index.json"


def list_videos(client: Any, bucket: str) -> list[Video]:
    videos = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.startswith(FRAMES_ROOT) or not key.lower().endswith(".mp4"):
                continue
            videos.append(Video(key=key, size=obj["Size"]))
    videos.sort(key=lambda v: v.key)
    return videos


def object_exists(client: Any, bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception as exc:  # botocore is imported lazily: read the code by duck typing
        code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        if code in MISSING_CODES:
            return False
        raise


@dataclass
class _VideoStats:
    duration: float = 0.0
    frame_count: int = 0
    download_s: float = 0.0
    extract_s: float = 0.0
    upload_s: float = 0.0


def _upload_frames(
    client: Any, bucket: str, frames: tuple[Path, ...], prefix: str, workers: int
) -> None:
    def upload(path: Path) -> None:
        client.upload_file(
            str(path), bucket, prefix + path.name,
            ExtraArgs={"ContentType": "image/jpeg"},
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(upload, frame) for frame in frames]
        for future in as_completed(futures):
            future.result()


def _process_video(
    client: Any,
    bucket: str,
    video: Video,
    extractor: FrameExtractor,
    fps: int,
    workers: int,
    workdir: Path | None,
    log: Callable[[str], None],
) -> _VideoStats:
    stats = _VideoStats()
    prefix = frames_prefix(video.key)
    with tempfile.TemporaryDirectory(prefix="frames-", dir=workdir) as tmp:
        tmp_dir = Path(tmp)
        video_path = tmp_dir / "video.mp4"
        frames_dir = tmp_dir / "frames"
        frames_dir.mkdir()

        start = time.perf_counter()
        client.download_file(bucket, video.key, str(video_path))
        stats.download_s = time.perf_counter() - start

        start = time.perf_counter()
        extracted = extractor.extract(video_path, frames_dir, fps)
        stats.extract_s = time.perf_counter() - start

        frames = extracted.frames
        timestamps = list(extracted.timestamps)
        if len(timestamps) != len(frames):
            log(f"  warning: {len(timestamps)} timestamps for {len(frames)} frames; using index/fps")
            timestamps = [extracted.start_time + i / fps for i in range(len(frames))]
        stats.duration = extracted.duration
        stats.frame_count = len(frames)

        start = time.perf_counter()
        _upload_frames(client, bucket, frames, prefix, workers)
        index = {
            "video_key": video.key,
            "fps": fps,
            "frame_count": len(frames),
            "duration": extracted.duration,
            "start_time": extracted.start_time,
            "frames": [
                {"key": prefix + frame.name, "timestamp": round(ts, 6)}
                for frame, ts in zip(frames, timestamps)
            ],
        }
        # index.json goes last: it is the completion marker for resumability.
        client.put_object(
            Bucket=bucket, Key=index_key(video.key),
            Body=json.dumps(index, indent=2).encode(),
            ContentType="application/json",
        )
        stats.upload_s = time.perf_counter() - start
    return stats


def _format_seconds(seconds: float) -> str:
    minutes, secs = divmod(int(round(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m{secs:02d}s" if hours else f"{minutes}m{secs:02d}s"


def run_frames(
    client: Any,
    bucket: str,
    extractor: FrameExtractor,
    workdir: Path | None = None,
    fps: int = DEFAULT_FPS,
    workers: int = DEFAULT_WORKERS,
    max_videos: int | None = None,
    dry_run: bool = False,
    log: Callable[[str], None] = _default_log,
) -> FramesReport:
    if workdir is not None:
        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)

    videos = list_videos(client, bucket)
    total_gb = sum(v.size for v in videos) / 1e9
    log(f"Found {len(videos)} videos ({total_gb:.2f} GB)")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        done = list(pool.map(lambda v: object_exists(client, bucket, index_key(v.key)), videos))
    report = FramesReport(
        skipped=[v.key for v, is_done in zip(videos, done) if is_done]
    )
    pending = [v for v, is_done in zip(videos, done) if not is_done]
    log(f"{len(report.skipped)} video(s) already done (index.json present), skipping")
    if max_videos is not None:
        report.deferred = [v.key for v in pending[max_videos:]]
        pending = pending[:max_videos]
    log(f"{len(pending)} video(s) to process")

    if dry_run:
        for video in pending:
            log(f"would process {video.key} ({video.size / 1e6:.1f} MB) -> {frames_prefix(video.key)}")
        return report

    all_stats: list[_VideoStats] = []
    for n, video in enumerate(pending, 1):
        log(f"[{n}/{len(pending)}] {video.key} ({video.size / 1e6:.1f} MB)")
        try:
            stats = _process_video(
                client, bucket, video, extractor, fps, workers, workdir, log)
        except Exception as exc:  # noqa: BLE001 - keep going; the video stays pending
            report.failed[video.key] = str(exc)
            log(f"  FAILED: {exc}")
            continue
        report.processed.append(video.key)
        all_stats.append(stats)
        log(
            f"  duration {stats.duration:.1f}s | frames {stats.frame_count} | "
            f"download {stats.download_s:.1f}s | extract {stats.extract_s:.1f}s | "
            f"upload {stats.upload_s:.1f}s"
        )

    if all_stats:
        log(
            "Totals: "
            f"download {_format_seconds(sum(s.download_s for s in all_stats))}, "
            f"extract {_format_seconds(sum(s.extract_s for s in all_stats))}, "
            f"upload {_format_seconds(sum(s.upload_s for s in all_stats))}, "
            f"{sum(s.frame_count for s in all_stats)} frames"
        )
    log(f"Done: {len(report.processed)} ok, {len(report.failed)} failed")
    return report


def _build_client(config: Mapping[str, str], workers: int) -> Any:
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=config["endpoint"],
        aws_access_key_id=config["access_key_id"],
        aws_secret_access_key=config["secret_access_key"],
        region_name="auto",
        config=Config(
            max_pool_connections=workers + 4,
            retries={"max_attempts": 10, "mode": "adaptive"},
        ),
    )


def _limit_from_env(env: Mapping[str, str]) -> int | None:
    value = env.get("MAX_FRAME_VIDEOS_PER_RUN")
    return int(value) if value else None


def _parse_args(argv: list[str] | None, env: Mapping[str, str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m ingest.frames",
        description=(__doc__ or "").strip().splitlines()[0],
    )
    parser.add_argument(
        "--limit", type=int,
        default=_limit_from_env(env),
        help="process at most N pending videos (default: MAX_FRAME_VIDEOS_PER_RUN, "
             "unset means no limit)",
    )
    parser.add_argument("--dry-run", action="store_true", help="only list what would be done")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help=f"concurrent uploads (default: {DEFAULT_WORKERS})")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS,
                        help=f"frames per second (default: {DEFAULT_FPS})")
    parser.add_argument("--tmp-dir", help="parent directory for temporary files")
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    env: MutableMapping[str, str] | None = None,
    dotenv_path: Path | None = None,
    client_factory: Callable[[Mapping[str, str], int], Any] = _build_client,
    extractor: FrameExtractor | None = None,
) -> int:
    env = os.environ if env is None else env
    load_dotenv_file(
        dotenv_path or Path(__file__).resolve().parent.parent / ".env", env)
    args = _parse_args(argv, env)
    bucket = env.get("R2_BUCKET_NAME") or env.get("R2_BUCKET")
    missing = [n for n in R2_REQUIRED if not env.get(n)]
    if not bucket:
        missing.append("R2_BUCKET_NAME")
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}",
              file=sys.stderr)
        return 1

    config = {
        "bucket": bucket,
        "endpoint": env.get("R2_ENDPOINT")
        or f"https://{env['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        "access_key_id": env["R2_ACCESS_KEY_ID"],
        "secret_access_key": env["R2_SECRET_ACCESS_KEY"],
    }
    workdir = args.tmp_dir or env.get("WORKDIR")
    report = run_frames(
        client=client_factory(config, args.workers),
        bucket=bucket,
        extractor=extractor or FfmpegFrameExtractor(),
        workdir=Path(workdir) if workdir else None,
        fps=args.fps,
        workers=args.workers,
        max_videos=args.limit,
        dry_run=args.dry_run,
        log=lambda message: print(redact(message, env), flush=True),
    )
    return 1 if report.failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001 - report without a traceback
        _default_log(f"Error: {type(exc).__name__}: {exc}")
        sys.exit(1)
