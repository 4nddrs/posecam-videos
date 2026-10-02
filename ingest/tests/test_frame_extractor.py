import json
import subprocess
from pathlib import Path

import pytest

from ingest.adapters import frames as frames_mod
from ingest.adapters.frames import FfmpegFrameExtractor
from ingest.ports import ExtractedFrames

SHOWINFO = (
    "[Parsed_showinfo_1 @ 0x7f] n:   {n} pts:{pts:>7} pts_time:{ts}       pos: 1\n"
)


class FakeRunner:
    def __init__(self, timestamps=("0", "0.2", "0.4"), frame_names=None,
                 ffmpeg_rc=0, ffmpeg_stderr=None, probe_info=None):
        self.calls = []
        self.timestamps = timestamps
        self.frame_names = (
            ["frame_000002.jpg", "frame_000001.jpg", "frame_000003.jpg"]
            if frame_names is None else frame_names
        )
        self.ffmpeg_rc = ffmpeg_rc
        self.ffmpeg_stderr = ffmpeg_stderr
        self.probe_info = probe_info or {
            "format": {"duration": "12.5", "start_time": "0.033"}
        }

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        if Path(argv[0]).name.startswith("ffprobe"):
            return subprocess.CompletedProcess(
                argv, 0, json.dumps(self.probe_info), ""
            )
        if self.ffmpeg_rc == 0:
            for name in self.frame_names:
                (Path(argv[-1]).parent / name).write_bytes(b"jpg")
        stderr = self.ffmpeg_stderr
        if stderr is None:
            stderr = "banner line without timestamp\n" + "".join(
                SHOWINFO.format(n=i, pts=i, ts=ts)
                for i, ts in enumerate(self.timestamps)
            )
        return subprocess.CompletedProcess(argv, self.ffmpeg_rc, "", stderr)


def _extract(tmp_path, runner, **kwargs):
    out = tmp_path / "frames"
    out.mkdir()
    video = tmp_path / "video.mp4"
    return FfmpegFrameExtractor(runner=runner, **kwargs).extract(video, out, 5), out


def test_ffprobe_argv_matches_the_original_script(tmp_path):
    runner = FakeRunner()
    _extract(tmp_path, runner)

    argv, kwargs = runner.calls[0]
    assert argv == [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries",
        "format=duration,start_time:stream=r_frame_rate,avg_frame_rate,nb_frames",
        "-of", "json", str(tmp_path / "video.mp4"),
    ]
    assert kwargs == {"check": True, "capture_output": True, "text": True}


def test_ffmpeg_argv_matches_the_original_script(tmp_path):
    runner = FakeRunner()
    _, out = _extract(tmp_path, runner)

    argv, kwargs = runner.calls[1]
    assert argv == [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "info",
        "-i", str(tmp_path / "video.mp4"),
        "-vf", "fps=5,showinfo",
        "-vsync", "passthrough",
        "-q:v", "3",
        str(out / "frame_%06d.jpg"),
    ]
    assert kwargs == {"capture_output": True, "text": True}


def test_returns_sorted_frames_timestamps_duration_and_start_time(tmp_path):
    result, out = _extract(tmp_path, FakeRunner())

    assert isinstance(result, ExtractedFrames)
    assert [p.name for p in result.frames] == [
        "frame_000001.jpg", "frame_000002.jpg", "frame_000003.jpg"]
    assert all(p.parent == out for p in result.frames)
    assert list(result.timestamps) == [0.0, 0.2, 0.4]
    assert result.duration == 12.5
    assert result.start_time == 0.033


def test_start_time_defaults_to_zero_when_probe_omits_it(tmp_path):
    runner = FakeRunner(probe_info={"format": {"duration": "3.0"}})
    result, _ = _extract(tmp_path, runner)
    assert result.start_time == 0.0


def test_negative_timestamps_are_parsed(tmp_path):
    result, _ = _extract(tmp_path, FakeRunner(timestamps=("-0.033", "0.167", "0.367")))
    assert list(result.timestamps) == [-0.033, 0.167, 0.367]


def test_ffmpeg_nonzero_exit_raises_with_last_ten_stderr_lines(tmp_path):
    stderr = "\n".join(f"line {i}" for i in range(30)) + "\n"
    runner = FakeRunner(ffmpeg_rc=1, ffmpeg_stderr=stderr)
    with pytest.raises(RuntimeError) as err:
        _extract(tmp_path, runner)

    message = str(err.value)
    assert message.startswith("ffmpeg failed (1):\n")
    assert message.splitlines()[1:] == [f"line {i}" for i in range(20, 30)]


def test_raises_when_no_frames_were_written(tmp_path):
    with pytest.raises(RuntimeError, match="ffmpeg produced no frames"):
        _extract(tmp_path, FakeRunner(frame_names=[]))


def test_binaries_come_from_arguments(tmp_path):
    runner = FakeRunner()
    _extract(tmp_path, runner, ffmpeg_bin="/opt/ffmpeg", ffprobe_bin="/opt/ffprobe")
    assert runner.calls[0][0][0] == "/opt/ffprobe"
    assert runner.calls[1][0][0] == "/opt/ffmpeg"


def test_binaries_come_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("FFMPEG_BIN", "/env/ffmpeg")
    monkeypatch.setenv("FFPROBE_BIN", "/env/ffprobe")
    runner = FakeRunner()
    _extract(tmp_path, runner)
    assert runner.calls[0][0][0] == "/env/ffprobe"
    assert runner.calls[1][0][0] == "/env/ffmpeg"


def test_probe_binary_is_derived_from_ffmpeg_binary(tmp_path, monkeypatch):
    monkeypatch.delenv("FFMPEG_BIN", raising=False)
    monkeypatch.delenv("FFPROBE_BIN", raising=False)
    runner = FakeRunner()
    _extract(tmp_path, runner, ffmpeg_bin="/opt/ffmpeg")
    assert runner.calls[0][0][0] == "/opt/ffprobe"


def test_constants_are_frozen():
    assert frames_mod.JPEG_QUALITY == 3
    assert frames_mod.FRAME_PATTERN == "frame_%06d.jpg"
