import json
from pathlib import Path

import pytest

from ingest import frames as frames_mod
from ingest.frames import frames_prefix, index_key, list_videos, run_frames
from ingest.ports import ExtractedFrames


class FakeClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakePaginator:
    def __init__(self, pages):
        self.pages = pages

    def paginate(self, Bucket):
        return iter(self.pages)


class FakeS3:
    def __init__(self, keys=(), done=(), fail_download=(), head_error=None):
        self.keys = list(keys)
        self.done = set(done)
        self.fail_download = set(fail_download)
        self.head_error = head_error
        self.events = []

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        half = len(self.keys) // 2 or 1
        pages = [
            {"Contents": [{"Key": k, "Size": 10} for k in self.keys[:half]]},
            {"Contents": [{"Key": k, "Size": 10} for k in self.keys[half:]]},
            {},
        ]
        return FakePaginator(pages)

    def head_object(self, Bucket, Key):
        if self.head_error is not None:
            raise FakeClientError(self.head_error)
        if Key in self.done:
            return {}
        raise FakeClientError("404")

    def download_file(self, bucket, key, local):
        self.events.append(("download", key))
        if key in self.fail_download:
            raise RuntimeError("boom")
        Path(local).write_bytes(b"video")

    def upload_file(self, local, bucket, key, ExtraArgs=None):
        self.events.append(("upload", key, ExtraArgs, Path(local).read_bytes()))

    def put_object(self, **kwargs):
        self.events.append(("put", kwargs))


class FakeExtractor:
    def __init__(self, count=3, timestamps=None, duration=12.5, start_time=0.5):
        self.count = count
        self.timestamps = timestamps
        self.duration = duration
        self.start_time = start_time
        self.calls = []

    def extract(self, video_path, out_dir, fps):
        self.calls.append((Path(video_path), Path(out_dir), fps))
        names = [f"frame_{i:06d}.jpg" for i in range(1, self.count + 1)]
        for name in names:
            (Path(out_dir) / name).write_bytes(name.encode())
        timestamps = (
            [i / fps for i in range(self.count)]
            if self.timestamps is None else self.timestamps
        )
        return ExtractedFrames(
            frames=tuple(Path(out_dir) / n for n in names),
            timestamps=tuple(timestamps),
            duration=self.duration,
            start_time=self.start_time,
        )


class FlakyExtractor(FakeExtractor):
    def __init__(self, bad_marker, **kwargs):
        super().__init__(**kwargs)
        self.bad_marker = bad_marker
        self.seen = 0

    def extract(self, video_path, out_dir, fps):
        self.seen += 1
        if self.seen == self.bad_marker:
            raise RuntimeError("ffmpeg failed (1):\nboom")
        return super().extract(video_path, out_dir, fps)


def _run(tmp_path, client, extractor=None, **kwargs):
    return run_frames(
        client=client, bucket="b", extractor=extractor or FakeExtractor(),
        workdir=tmp_path / "work", log=lambda message: None, **kwargs,
    )


def _puts(client):
    return [e[1] for e in client.events if e[0] == "put"]


def test_list_videos_filters_and_sorts_by_key():
    client = FakeS3(keys=[
        "2026-01-02/b.mp4", "frames/2026-01-01/a/frame_000001.jpg",
        "2026-01-01/a.MP4", "2026-01-01/a.jpg", "frames/x.mp4",
        "2026-01-01/notes.txt", "2026-01-01/Z.Mp4",
    ])
    assert [v.key for v in list_videos(client, "b")] == [
        "2026-01-01/Z.Mp4", "2026-01-01/a.MP4", "2026-01-02/b.mp4"]


def test_prefix_and_index_key_drop_only_the_extension():
    assert frames_prefix("2026-01-01/a.mp4") == "frames/2026-01-01/a/"
    assert index_key("2026-01-01/a.mp4") == "frames/2026-01-01/a/index.json"
    assert frames_prefix("2026-01-01/clip.v2 final.MP4") == (
        "frames/2026-01-01/clip.v2 final/")
    assert index_key("2026-01-01/clip.v2 final.MP4") == (
        "frames/2026-01-01/clip.v2 final/index.json")


def test_done_videos_are_skipped_and_not_downloaded(tmp_path):
    client = FakeS3(
        keys=["d/a.mp4", "d/b.mp4"], done={"frames/d/a/index.json"})
    report = _run(tmp_path, client)

    assert report.skipped == ["d/a.mp4"]
    assert report.processed == ["d/b.mp4"]
    assert [e[1] for e in client.events if e[0] == "download"] == ["d/b.mp4"]


def test_head_error_other_than_missing_is_reraised(tmp_path):
    client = FakeS3(keys=["d/a.mp4"], head_error="403")
    with pytest.raises(FakeClientError):
        _run(tmp_path, client)


@pytest.mark.parametrize("code", ["404", "NoSuchKey", "NotFound"])
def test_missing_error_codes_mean_pending(tmp_path, code):
    client = FakeS3(keys=["d/a.mp4"], head_error=code)
    assert _run(tmp_path, client).processed == ["d/a.mp4"]


def test_uploads_frames_with_exact_keys_and_content_type(tmp_path):
    client = FakeS3(keys=["2026-01-01/clip.v2 a.mp4"])
    _run(tmp_path, client, FakeExtractor(count=3))

    uploads = [e for e in client.events if e[0] == "upload"]
    assert sorted((e[1], e[2], e[3]) for e in uploads) == [
        (f"frames/2026-01-01/clip.v2 a/frame_{i:06d}.jpg",
         {"ContentType": "image/jpeg"}, f"frame_{i:06d}.jpg".encode())
        for i in (1, 2, 3)
    ]


def test_index_json_body_is_exact_and_written_last(tmp_path):
    client = FakeS3(keys=["d/a.mp4"])
    extractor = FakeExtractor(
        count=2, timestamps=[0.5, 0.7000004], duration=12.5, start_time=0.5)
    _run(tmp_path, client, extractor, fps=5)

    kinds = [e[0] for e in client.events]
    assert kinds == ["download", "upload", "upload", "put"]
    (put,) = _puts(client)
    assert put["Bucket"] == "b"
    assert put["Key"] == "frames/d/a/index.json"
    assert put["ContentType"] == "application/json"
    expected = {
        "video_key": "d/a.mp4",
        "fps": 5,
        "frame_count": 2,
        "duration": 12.5,
        "start_time": 0.5,
        "frames": [
            {"key": "frames/d/a/frame_000001.jpg", "timestamp": 0.5},
            {"key": "frames/d/a/frame_000002.jpg", "timestamp": 0.7},
        ],
    }
    assert put["Body"] == json.dumps(expected, indent=2).encode()
    assert list(json.loads(put["Body"])) == [
        "video_key", "fps", "frame_count", "duration", "start_time", "frames"]


def test_timestamp_mismatch_falls_back_to_start_time_plus_index_over_fps(tmp_path):
    client = FakeS3(keys=["d/a.mp4"])
    logs = []
    extractor = FakeExtractor(count=3, timestamps=[9.0], start_time=1.0)
    run_frames(
        client=client, bucket="b", extractor=extractor, workdir=tmp_path / "w",
        fps=4, log=logs.append,
    )

    (put,) = _puts(client)
    stamps = [f["timestamp"] for f in json.loads(put["Body"])["frames"]]
    assert stamps == [1.0, 1.25, 1.5]
    assert any("warning: 1 timestamps for 3 frames; using index/fps" in m
               for m in logs)


def test_extractor_receives_fps_and_a_temp_dir_under_workdir(tmp_path):
    client = FakeS3(keys=["d/a.mp4"])
    extractor = FakeExtractor()
    _run(tmp_path, client, extractor, fps=2)

    (video_path, out_dir, fps), = extractor.calls
    assert fps == 2
    assert tmp_path / "work" in video_path.parents
    assert tmp_path / "work" in out_dir.parents


def test_temp_dir_is_removed_after_success_and_failure(tmp_path):
    client = FakeS3(keys=["d/a.mp4", "d/b.mp4"], fail_download={"d/a.mp4"})
    _run(tmp_path, client)
    assert list((tmp_path / "work").iterdir()) == []


def test_failing_video_does_not_stop_run_and_gets_no_index(tmp_path):
    client = FakeS3(keys=["d/a.mp4", "d/b.mp4", "d/c.mp4"])
    report = _run(tmp_path, client, FlakyExtractor(bad_marker=2))

    assert report.processed == ["d/a.mp4", "d/c.mp4"]
    assert list(report.failed) == ["d/b.mp4"]
    assert "boom" in report.failed["d/b.mp4"]
    assert [p["Key"] for p in _puts(client)] == [
        "frames/d/a/index.json", "frames/d/c/index.json"]


def test_failed_upload_leaves_video_pending_without_index(tmp_path):
    client = FakeS3(keys=["d/a.mp4"])

    def boom(*args, **kwargs):
        raise RuntimeError("upload failed")

    client.upload_file = boom
    report = _run(tmp_path, client)

    assert list(report.failed) == ["d/a.mp4"]
    assert _puts(client) == []


def test_max_videos_limits_pending_and_reports_the_rest_as_deferred(tmp_path):
    client = FakeS3(keys=["d/a.mp4", "d/b.mp4", "d/c.mp4"], done={"frames/d/a/index.json"})
    report = _run(tmp_path, client, max_videos=1)

    assert report.skipped == ["d/a.mp4"]
    assert report.processed == ["d/b.mp4"]
    assert report.deferred == ["d/c.mp4"]


def test_failed_videos_do_not_consume_the_max_videos_cap(tmp_path):
    client = FakeS3(
        keys=["d/a.mp4", "d/b.mp4", "d/c.mp4", "d/d.mp4"],
        fail_download={"d/a.mp4", "d/b.mp4"})
    report = _run(tmp_path, client, max_videos=1)

    assert list(report.failed) == ["d/a.mp4", "d/b.mp4"]
    assert report.processed == ["d/c.mp4"]
    assert report.deferred == ["d/d.mp4"]


def test_max_videos_zero_processes_nothing(tmp_path):
    client = FakeS3(keys=["d/a.mp4", "d/b.mp4"])
    report = _run(tmp_path, client, max_videos=0)

    assert report.processed == [] and report.failed == {}
    assert report.deferred == ["d/a.mp4", "d/b.mp4"]
    assert client.events == []


def test_progress_logs_count_attempts_and_cap_under_the_new_limit(tmp_path):
    client = FakeS3(keys=["d/a.mp4", "d/b.mp4", "d/c.mp4"], fail_download={"d/a.mp4"})
    logs = []
    run_frames(
        client=client, bucket="b", extractor=FakeExtractor(),
        workdir=tmp_path / "w", max_videos=1, log=logs.append,
    )

    assert "3 video(s) pending, processing up to 1" in logs
    assert any(m.startswith("[1/3] d/a.mp4") for m in logs)
    assert any(m.startswith("[2/3] d/b.mp4") for m in logs)


def test_max_videos_dry_run_lists_the_first_pending_videos(tmp_path):
    client = FakeS3(keys=["d/a.mp4", "d/b.mp4", "d/c.mp4"])
    logs = []
    report = run_frames(
        client=client, bucket="b", extractor=FakeExtractor(),
        workdir=tmp_path / "w", max_videos=2, dry_run=True, log=logs.append,
    )

    assert [m.split()[2] for m in logs if m.startswith("would process")] == [
        "d/a.mp4", "d/b.mp4"]
    assert report.deferred == ["d/c.mp4"]


def test_failed_frame_upload_cancels_the_remaining_uploads(tmp_path):
    client = FakeS3(keys=["d/a.mp4"])
    attempted = []

    def upload(local, bucket, key, ExtraArgs=None):
        attempted.append(key)
        raise RuntimeError("upload failed")

    client.upload_file = upload
    report = _run(tmp_path, client, FakeExtractor(count=5), workers=1)

    assert list(report.failed) == ["d/a.mp4"]
    # With one worker at most one more upload can already be dequeued when the
    # failure is seen; the other three must never start.
    assert attempted[0] == "frames/d/a/frame_000001.jpg"
    assert len(attempted) <= 2
    assert _puts(client) == []


def test_dry_run_downloads_nothing(tmp_path):
    client = FakeS3(keys=["d/a.mp4"])
    logs = []
    report = run_frames(
        client=client, bucket="b", extractor=FakeExtractor(),
        workdir=tmp_path / "w", dry_run=True, log=logs.append,
    )

    assert client.events == []
    assert report.processed == []
    assert any(m.startswith("would process d/a.mp4") for m in logs)


def test_progress_and_total_log_lines(tmp_path):
    client = FakeS3(keys=["d/a.mp4"])
    logs = []
    run_frames(
        client=client, bucket="b", extractor=FakeExtractor(),
        workdir=tmp_path / "w", log=logs.append,
    )

    assert logs[0] == "Found 1 videos (0.00 GB)"
    assert "0 video(s) already done (index.json present), skipping" in logs
    assert "1 video(s) to process" in logs
    assert any(m.startswith("[1/1] d/a.mp4") for m in logs)
    assert any(m.startswith("Totals: ") and m.endswith("3 frames") for m in logs)
    assert logs[-1] == "Done: 1 ok, 0 failed"


# main()

R2_ENV = {
    "R2_ACCOUNT_ID": "acct-id-1234",
    "R2_ACCESS_KEY_ID": "access-key-1234",
    "R2_SECRET_ACCESS_KEY": "secret-key-1234",
    "R2_BUCKET_NAME": "bucket",
}


def _main(tmp_path, env, argv=(), client=None, extractor=None):
    built = {}

    def factory(config, workers):
        built["config"], built["workers"] = config, workers
        return client

    code = frames_mod.main(
        list(argv), env=env, dotenv_path=tmp_path / "missing.env",
        client_factory=factory, extractor=extractor or FakeExtractor(),
    )
    return code, built


def test_main_fails_clearly_when_r2_variables_are_missing(tmp_path, capsys):
    code, _ = _main(tmp_path, {"R2_ACCOUNT_ID": "x"})

    err = capsys.readouterr().err
    assert code == 1
    assert "R2_ACCESS_KEY_ID" in err
    assert "R2_SECRET_ACCESS_KEY" in err
    assert "R2_BUCKET_NAME" in err
    assert "DRIVE" not in err and "GOOGLE" not in err
    assert "R2_PUBLIC_BASE_URL" not in err


def test_main_needs_no_drive_variables(tmp_path):
    client = FakeS3(keys=["d/a.mp4"])
    code, built = _main(tmp_path, dict(R2_ENV), ["--tmp-dir", str(tmp_path / "t")],
                        client=client)

    assert code == 0
    assert built["config"]["bucket"] == "bucket"


def test_main_accepts_legacy_bucket_variable(tmp_path):
    env = {k: v for k, v in R2_ENV.items() if k != "R2_BUCKET_NAME"}
    env["R2_BUCKET"] = "legacy"
    _, built = _main(tmp_path, env, ["--tmp-dir", str(tmp_path / "t")],
                      client=FakeS3())
    assert built["config"]["bucket"] == "legacy"


def test_main_endpoint_defaults_and_override(tmp_path):
    _, built = _main(tmp_path, dict(R2_ENV), ["--tmp-dir", str(tmp_path / "t")],
                     client=FakeS3())
    assert built["config"]["endpoint"] == "https://acct-id-1234.r2.cloudflarestorage.com"

    env = dict(R2_ENV, R2_ENDPOINT="https://custom.example.com")
    _, built = _main(tmp_path, env, ["--tmp-dir", str(tmp_path / "t")], client=FakeS3())
    assert built["config"]["endpoint"] == "https://custom.example.com"


def test_main_passes_workers_to_the_client_factory(tmp_path):
    _, built = _main(tmp_path, dict(R2_ENV),
                     ["--workers", "7", "--tmp-dir", str(tmp_path / "t")],
                     client=FakeS3())
    assert built["workers"] == 7


def test_main_exit_code_is_one_when_a_video_failed(tmp_path):
    client = FakeS3(keys=["d/a.mp4"], fail_download={"d/a.mp4"})
    code, _ = _main(tmp_path, dict(R2_ENV), ["--tmp-dir", str(tmp_path / "t")],
                    client=client)
    assert code == 1


def test_main_limit_defaults_to_env_and_flag_overrides(tmp_path):
    keys = ["d/a.mp4", "d/b.mp4", "d/c.mp4"]
    env = dict(R2_ENV, MAX_FRAME_VIDEOS_PER_RUN="2")
    client = FakeS3(keys=keys)
    _main(tmp_path, env, ["--tmp-dir", str(tmp_path / "t")], client=client)
    assert [e[1] for e in client.events if e[0] == "download"] == ["d/a.mp4", "d/b.mp4"]

    client = FakeS3(keys=keys)
    _main(tmp_path, env, ["--limit", "1", "--tmp-dir", str(tmp_path / "t")],
          client=client)
    assert [e[1] for e in client.events if e[0] == "download"] == ["d/a.mp4"]


@pytest.mark.parametrize("value", [None, ""])
def test_main_limit_unset_or_empty_means_no_limit(tmp_path, value):
    env = dict(R2_ENV)
    if value is not None:
        env["MAX_FRAME_VIDEOS_PER_RUN"] = value
    client = FakeS3(keys=["d/a.mp4", "d/b.mp4"])
    _main(tmp_path, env, ["--tmp-dir", str(tmp_path / "t")], client=client)
    assert len([e for e in client.events if e[0] == "download"]) == 2


@pytest.mark.parametrize("argv, expected", [
    ([], 600), (["--timeout", "30"], 30), (["--timeout", "0"], None)])
def test_main_passes_the_timeout_to_the_extractor(tmp_path, monkeypatch, argv, expected):
    built = {}

    class RecordingExtractor(FakeExtractor):
        def __init__(self, timeout):
            super().__init__()
            built["timeout"] = timeout

    monkeypatch.setattr(frames_mod, "FfmpegFrameExtractor", RecordingExtractor)
    code = frames_mod.main(
        [*argv, "--tmp-dir", str(tmp_path / "t")], env=dict(R2_ENV),
        dotenv_path=tmp_path / "missing.env",
        client_factory=lambda config, workers: FakeS3(keys=["d/a.mp4"]),
    )

    assert code == 0
    assert built["timeout"] == expected


def test_main_dry_run_writes_nothing(tmp_path):
    client = FakeS3(keys=["d/a.mp4"])
    code, _ = _main(tmp_path, dict(R2_ENV), ["--dry-run"], client=client)
    assert code == 0 and client.events == []


def test_main_redacts_secret_values_from_output(tmp_path, capsys):
    client = FakeS3(keys=["secret-key-1234/a.mp4"])
    _main(tmp_path, dict(R2_ENV), ["--dry-run"], client=client)

    out = capsys.readouterr().out
    assert "secret-key-1234" not in out
    assert "<R2_SECRET_ACCESS_KEY>/a.mp4" in out


def test_redact_ignores_short_values():
    assert frames_mod.redact("abc", {"R2_ACCOUNT_ID": "abc"}) == "abc"
