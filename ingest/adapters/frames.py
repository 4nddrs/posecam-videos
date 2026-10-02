"""ffmpeg adapter implementing the FrameExtractor port.

The ffprobe and ffmpeg arguments are frozen: stored frames must stay
identical to the ones produced before this step joined the pipeline.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

from ingest.ports import ExtractedFrames

JPEG_QUALITY = 3
FRAME_PATTERN = "frame_%06d.jpg"
PTS_TIME_RE = re.compile(r"\bpts_time:\s*(-?[0-9.]+)")


class FfmpegFrameExtractor:
    def __init__(
        self,
        ffmpeg_bin: str | None = None,
        ffprobe_bin: str | None = None,
        runner: Callable[..., Any] = subprocess.run,
        timeout: float | None = 600,
    ) -> None:
        self._bin = ffmpeg_bin or os.environ.get("FFMPEG_BIN") or "ffmpeg"
        self._probe_bin = (
            ffprobe_bin
            or os.environ.get("FFPROBE_BIN")
            or self._bin.replace("ffmpeg", "ffprobe")
        )
        self._runner = runner
        self._timeout = timeout

    def _run(self, argv: list[str], **kwargs: Any) -> Any:
        try:
            return self._runner(argv, timeout=self._timeout, **kwargs)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"{Path(argv[0]).name} timed out after {self._timeout:g}s"
            ) from exc

    def _probe(self, path: Path) -> dict:
        result = self._run(
            [
                self._probe_bin, "-v", "error",
                "-select_streams", "v:0",
                "-show_entries",
                "format=duration,start_time:stream=r_frame_rate,avg_frame_rate,nb_frames",
                "-of", "json", str(path),
            ],
            check=True, capture_output=True, text=True,
        )
        return json.loads(result.stdout)

    def _timestamps(self, video_path: Path, out_dir: Path, fps: int) -> list[float]:
        """Run ffmpeg and return the presentation timestamp of every written frame.

        ``showinfo`` after ``fps`` logs the pts_time of each output frame, and
        ``-vsync passthrough`` keeps a 1:1 mapping between those frames and files.
        """
        result = self._run(
            [
                self._bin, "-hide_banner", "-nostdin", "-loglevel", "info",
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

    def extract(self, video_path: Path, out_dir: Path, fps: int) -> ExtractedFrames:
        video_path, out_dir = Path(video_path), Path(out_dir)
        info = self._probe(video_path)
        duration = float(info["format"]["duration"])
        start_time = float(info["format"].get("start_time", 0.0))

        timestamps = self._timestamps(video_path, out_dir, fps)
        frames = sorted(out_dir.glob("frame_*.jpg"))
        if not frames:
            raise RuntimeError("ffmpeg produced no frames")
        return ExtractedFrames(
            frames=tuple(frames),
            timestamps=tuple(timestamps),
            duration=duration,
            start_time=start_time,
        )
