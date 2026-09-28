"""ffmpeg adapter implementing the VideoProcessor port.

Produces a faststart-remuxed MP4 and a JPG poster. ffmpeg failures never
raise: the original video is kept and/or the poster is omitted.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from ingest.ports import ProcessedVideo


def _log(message: str) -> None:
    print(message, file=sys.stderr)


class FfmpegProcessor:
    def __init__(
        self,
        ffmpeg_bin: str = "ffmpeg",
        runner: Callable[..., Any] = subprocess.run,
    ) -> None:
        self._bin = ffmpeg_bin
        self._probe_bin = os.environ.get("FFPROBE_BIN") or (
            ffmpeg_bin.replace("ffmpeg", "ffprobe")
        )
        self._runner = runner

    def _run(self, args: list[str], out: Path) -> bool:
        argv = [self._bin, "-y", *args, str(out)]
        try:
            result = self._runner(argv, capture_output=True, check=False)
        except Exception as exc:  # noqa: BLE001 - never fail ingest on ffmpeg
            _log(f"ffmpeg failed to run: {exc}")
            return False
        if result.returncode != 0:
            stderr = getattr(result, "stderr", b"") or b""
            _log(f"ffmpeg exited {result.returncode}: {stderr[-500:]!r}")
            return False
        return out.exists()

    def probe(self, video_path: Path) -> float | None:
        argv = [
            self._probe_bin, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(video_path),
        ]
        try:
            result = self._runner(argv, capture_output=True, check=False)
            if result.returncode != 0:
                return None
            out = result.stdout or b""
            text = out.decode() if isinstance(out, bytes) else str(out)
            return float(text.strip())
        except Exception as exc:  # noqa: BLE001 - duration is best effort
            _log(f"ffprobe failed: {exc}")
            return None

    def process(self, video_path: Path, workdir: Path) -> ProcessedVideo:
        video_path = Path(video_path)
        out_dir = Path(workdir) / "processed"
        out_dir.mkdir(parents=True, exist_ok=True)

        remuxed = out_dir / video_path.name
        video = video_path
        if self._run(
            ["-i", str(video_path), "-c", "copy", "-movflags", "+faststart"], remuxed
        ):
            video = remuxed

        poster = out_dir / f"{video_path.stem}.jpg"
        poster_path: Path | None = poster
        if not self._run(
            ["-ss", "1", "-i", str(video), "-frames:v", "1",
             "-vf", "scale=640:-2", "-q:v", "4"],
            poster,
        ):
            poster_path = None
        return ProcessedVideo(
            video_path=video,
            poster_path=poster_path,
            duration_seconds=self.probe(video),
        )


class NoopProcessor:
    def probe(self, video_path: Path) -> float | None:
        return None

    def process(self, video_path: Path, workdir: Path) -> ProcessedVideo:
        return ProcessedVideo(video_path=Path(video_path), poster_path=None)


def build_processor() -> FfmpegProcessor | NoopProcessor:
    binary = os.environ.get("FFMPEG_BIN") or "ffmpeg"
    if shutil.which(binary):
        return FfmpegProcessor(ffmpeg_bin=binary)
    _log(f"{binary} not found; posters and faststart disabled")
    return NoopProcessor()
