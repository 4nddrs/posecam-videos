import subprocess
from pathlib import Path

from ingest.adapters import ffmpeg as ffmpeg_mod
from ingest.adapters.ffmpeg import FfmpegProcessor, NoopProcessor, build_processor


class FakeRunner:
    def __init__(self, fail_remux=False, fail_poster=False):
        self.calls = []
        self.fail_remux = fail_remux
        self.fail_poster = fail_poster

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        out = Path(argv[-1])
        is_poster = out.suffix == ".jpg"
        failed = self.fail_poster if is_poster else self.fail_remux
        if failed:
            return subprocess.CompletedProcess(argv, 1, b"", b"boom")
        out.write_bytes(b"x")
        return subprocess.CompletedProcess(argv, 0, b"", b"")


def _video(tmp_path):
    p = tmp_path / "clip.mp4"
    p.write_bytes(b"orig")
    work = tmp_path / "work"
    work.mkdir()
    return p, work


def test_process_remuxes_faststart_and_makes_poster(tmp_path):
    video, work = _video(tmp_path)
    runner = FakeRunner()
    result = FfmpegProcessor("ffmpeg", runner=runner).process(video, work)

    remux, poster = runner.calls
    assert remux[0] == "ffmpeg"
    assert "+faststart" in remux and "-c" in remux and "copy" in remux
    assert "scale=640:-2" in poster
    assert result.video_path.name == "clip.mp4" and result.video_path != video
    assert result.poster_path is not None and result.poster_path.suffix == ".jpg"
    assert result.poster_path.stem == "clip"


def test_remux_failure_falls_back_to_original(tmp_path):
    video, work = _video(tmp_path)
    result = FfmpegProcessor(runner=FakeRunner(fail_remux=True)).process(video, work)
    assert result.video_path == video


def test_poster_failure_gives_none(tmp_path):
    video, work = _video(tmp_path)
    result = FfmpegProcessor(runner=FakeRunner(fail_poster=True)).process(video, work)
    assert result.poster_path is None


def test_runner_exception_never_raises(tmp_path):
    video, work = _video(tmp_path)

    def boom(argv, **kw):
        raise OSError("no ffmpeg")

    result = FfmpegProcessor(runner=boom).process(video, work)
    assert result.video_path == video and result.poster_path is None


def test_noop_processor(tmp_path):
    video, work = _video(tmp_path)
    result = NoopProcessor().process(video, work)
    assert result.video_path == video and result.poster_path is None


def test_build_processor_noop_without_ffmpeg(monkeypatch):
    monkeypatch.delenv("FFMPEG_BIN", raising=False)
    monkeypatch.setattr(ffmpeg_mod.shutil, "which", lambda name: None)
    assert isinstance(build_processor(), NoopProcessor)


def test_build_processor_uses_ffmpeg_when_found(monkeypatch):
    monkeypatch.delenv("FFMPEG_BIN", raising=False)
    monkeypatch.setattr(ffmpeg_mod.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    assert isinstance(build_processor(), FfmpegProcessor)
