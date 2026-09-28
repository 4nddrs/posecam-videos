import json
from pathlib import Path

from ingest.ports import ProcessedVideo
from ingest.posters import run_posters

BASE = "https://cdn.example.com"


class FakeClient:
    def __init__(self, fail_keys=()):
        self.calls = []
        self.fail_keys = set(fail_keys)

    def download_file(self, bucket, key, local):
        self.calls.append(("download", bucket, key))
        if key in self.fail_keys:
            raise RuntimeError("boom")
        Path(local).write_bytes(b"video")

    def upload_file(self, local, bucket, key, ExtraArgs=None):
        self.calls.append(("upload", bucket, key, Path(local).name))


class FakeProcessor:
    def process(self, video_path, workdir):
        out = Path(workdir) / "processed"
        out.mkdir(parents=True, exist_ok=True)
        remux = out / Path(video_path).name
        remux.write_bytes(b"remux")
        poster = out / f"{Path(video_path).stem}.jpg"
        poster.write_bytes(b"jpg")
        return ProcessedVideo(video_path=remux, poster_path=poster, duration_seconds=9.5)

    def probe(self, video_path):
        return 9.5


def _write_manifest(path, entries):
    videos = [
        {"id": i, "name": i.split("/")[-1], "url": f"{BASE}/{i}",
         "poster": p, "duration": 5.0, "source_zip": "z"}
        for i, p in entries
    ]
    path.write_text(json.dumps({"generated_at": "x", "days": [
        {"day": "2026-01-01", "videos": videos}]}))


def _null_durations(path):
    data = json.loads(path.read_text())
    for d in data["days"]:
        for v in d["videos"]:
            v["duration"] = None
    path.write_text(json.dumps(data))


def _durations(path):
    data = json.loads(path.read_text())
    return {v["id"]: v.get("duration") for d in data["days"] for v in d["videos"]}


def _posters(path):
    data = json.loads(path.read_text())
    return {v["id"]: v["poster"] for d in data["days"] for v in d["videos"]}


def _run(tmp_path, client=None, max_items=10):
    return run_posters(
        manifest_path=tmp_path / "m.json", bucket="b",
        client=client or FakeClient(), processor=FakeProcessor(),
        public_base_url=BASE, workdir=tmp_path / "work", max_items=max_items,
    )


def test_processes_only_entries_without_poster(tmp_path):
    _write_manifest(tmp_path / "m.json", [
        ("2026-01-01/a.mp4", None), ("2026-01-01/b.mp4", f"{BASE}/2026-01-01/b.jpg")])
    client = FakeClient()
    report = _run(tmp_path, client)
    assert report["updated"] == ["2026-01-01/a.mp4"]
    assert [c for c in client.calls if c[0] == "download"] == [
        ("download", "b", "2026-01-01/a.mp4")]


def test_uploads_poster_and_remuxed_video(tmp_path):
    _write_manifest(tmp_path / "m.json", [("2026-01-01/a.mp4", None)])
    client = FakeClient()
    _run(tmp_path, client)
    uploads = [c for c in client.calls if c[0] == "upload"]
    assert ("upload", "b", "2026-01-01/a.mp4", "a.mp4") in uploads
    assert ("upload", "b", "2026-01-01/a.jpg", "a.jpg") in uploads


def test_updates_manifest_poster(tmp_path):
    _write_manifest(tmp_path / "m.json", [("2026-01-01/a.mp4", None)])
    _run(tmp_path)
    assert _posters(tmp_path / "m.json") == {
        "2026-01-01/a.mp4": f"{BASE}/2026-01-01/a.jpg"}


def test_saves_after_each_item(tmp_path):
    _write_manifest(tmp_path / "m.json", [
        ("2026-01-01/a.mp4", None), ("2026-01-01/b.mp4", None)])
    seen = []

    class Spy(FakeClient):
        def download_file(self, bucket, key, local):
            seen.append(_posters(tmp_path / "m.json"))
            super().download_file(bucket, key, local)

    _run(tmp_path, Spy())
    assert seen[0]["2026-01-01/a.mp4"] is None
    assert seen[1]["2026-01-01/a.mp4"] is not None


def test_honors_max_items_and_reports_remaining(tmp_path):
    _write_manifest(tmp_path / "m.json", [
        ("2026-01-01/a.mp4", None), ("2026-01-01/b.mp4", None),
        ("2026-01-01/c.mp4", None)])
    report = _run(tmp_path, max_items=2)
    assert len(report["updated"]) == 2
    assert report["remaining"] == 1


def test_records_failures_without_aborting(tmp_path):
    _write_manifest(tmp_path / "m.json", [
        ("2026-01-01/a.mp4", None), ("2026-01-01/b.mp4", None)])
    report = _run(tmp_path, FakeClient(fail_keys=["2026-01-01/a.mp4"]))
    assert report["updated"] == ["2026-01-01/b.mp4"]
    assert "2026-01-01/a.mp4" in report["failed"]
    assert report["remaining"] == 1


def test_records_duration_for_new_posters(tmp_path):
    _write_manifest(tmp_path / "m.json", [("2026-01-01/a.mp4", None)])
    _null_durations(tmp_path / "m.json")
    _run(tmp_path)
    assert _durations(tmp_path / "m.json") == {"2026-01-01/a.mp4": 9.5}


def test_backfills_duration_without_uploading(tmp_path):
    _write_manifest(tmp_path / "m.json", [
        ("2026-01-01/b.mp4", f"{BASE}/2026-01-01/b.jpg")])
    _null_durations(tmp_path / "m.json")
    client = FakeClient()
    report = _run(tmp_path, client)
    assert _durations(tmp_path / "m.json") == {"2026-01-01/b.mp4": 9.5}
    assert [c for c in client.calls if c[0] == "upload"] == []
    assert report["durations"] == ["2026-01-01/b.mp4"]
    assert _posters(tmp_path / "m.json") == {"2026-01-01/b.mp4": f"{BASE}/2026-01-01/b.jpg"}
