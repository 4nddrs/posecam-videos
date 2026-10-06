import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from ingest.ports import ZipEntry
from ingest.sidecars import run_sidecars

BASE = "https://cdn.example.com"


class FakeSource:
    """In-memory ZipSource: builds real zip files from member bytes."""

    def __init__(self, zips):
        # zips: {zip_name: {member_name: bytes}}
        self._zips = zips
        self.downloaded = []

    def list_zips(self):
        return [
            ZipEntry(id=name, name=name,
                     uploaded_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
            for name in self._zips
        ]

    def download(self, entry, dest):
        dest = Path(dest)
        target = dest / entry.name if dest.is_dir() else dest
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target, "w") as zf:
            for member, content in self._zips[entry.name].items():
                zf.writestr(member, content)
        self.downloaded.append(entry.name)
        return target


class FakeClient:
    def __init__(self):
        self.uploads = []

    def upload_file(self, local, bucket, key, ExtraArgs=None):
        self.uploads.append((key, ExtraArgs))


class FakePublisher:
    def __init__(self):
        self.published = []

    def publish_manifest(self, manifest_path):
        self.published.append(Path(manifest_path))
        return "ok"


def _video(vid, name, source_zip):
    return {
        "id": vid, "name": name, "url": f"{BASE}/{vid}", "poster": None,
        "duration": 1.0, "source_zip": source_zip, "category": "c", "uploader": "u",
    }


def _write_manifest(path, videos, day="2026-01-01"):
    path.write_text(json.dumps({
        "generated_at": "x",
        "days": [{"day": day, "videos": videos}],
    }))


def _write_manifest_days(path, days):
    path.write_text(json.dumps({
        "generated_at": "x",
        "days": [{"day": day, "videos": videos} for day, videos in days.items()],
    }))


def _videos_of(path):
    data = json.loads(Path(path).read_text())
    return {v["id"]: v for d in data["days"] for v in d["videos"]}


def _run(tmp_path, source, client=None, publisher=None, **kwargs):
    client = client or FakeClient()
    publisher = publisher or FakePublisher()
    report = run_sidecars(
        manifest_path=tmp_path / "m.json",
        source=source,
        publisher=publisher,
        r2_client=client,
        bucket="b",
        public_base_url=BASE,
        workdir=tmp_path / "work",
        **kwargs,
    )
    return report, client, publisher


def test_pairs_sidecars_by_stem_and_records_metadata(tmp_path):
    _write_manifest(tmp_path / "m.json",
                    [_video("2026-01-01/clip.mp4", "clip.mp4", "z.zip")])
    source = FakeSource({"z.zip": {
        "clip.mp4": b"video", "clip.txt": b"text", "clip.json": b"{}"}})

    report, client, publisher = _run(tmp_path, source)

    assert report["processed"] == ["z.zip"]
    assert sorted(key for key, _ in client.uploads) == [
        "2026-01-01/clip.json", "2026-01-01/clip.txt"]
    assert report["missing"] == []
    assert report["unmatched"] == []
    assert publisher.published == [tmp_path / "m.json"]

    video = _videos_of(tmp_path / "m.json")["2026-01-01/clip.mp4"]
    assert video["metadata"]["txt"] == f"{BASE}/2026-01-01/clip.txt"
    assert video["metadata"]["json"] == f"{BASE}/2026-01-01/clip.json"


def test_uploads_correct_content_types(tmp_path):
    _write_manifest(tmp_path / "m.json",
                    [_video("2026-01-01/clip.mp4", "clip.mp4", "z.zip")])
    source = FakeSource({"z.zip": {"clip.mp4": b"v", "clip.txt": b"t", "clip.json": b"{}"}})

    _, client, _ = _run(tmp_path, source)

    types = {key: extra["ContentType"] for key, extra in client.uploads}
    assert types["2026-01-01/clip.txt"] == "text/plain; charset=utf-8"
    assert types["2026-01-01/clip.json"] == "application/json"


def test_unmatched_sidecar_is_reported(tmp_path):
    _write_manifest(tmp_path / "m.json",
                    [_video("2026-01-01/clip.mp4", "clip.mp4", "z.zip")])
    source = FakeSource({"z.zip": {"clip.mp4": b"v", "orphan.txt": b"x"}})

    report, client, _ = _run(tmp_path, source)

    assert client.uploads == []
    assert report["unmatched"] == [
        {"zip": "z.zip", "sidecar": "orphan.txt", "reason": "no matching video"}]


def test_video_without_sidecar_is_missing(tmp_path):
    _write_manifest(tmp_path / "m.json",
                    [_video("2026-01-01/clip.mp4", "clip.mp4", "z.zip")])
    source = FakeSource({"z.zip": {"clip.mp4": b"v"}})

    report, _, _ = _run(tmp_path, source)

    assert report["missing"] == ["2026-01-01/clip.mp4"]


def test_skips_existing_metadata_unless_forced(tmp_path):
    video = _video("2026-01-01/clip.mp4", "clip.mp4", "z.zip")
    video["metadata"] = {"txt": f"{BASE}/old.txt"}
    _write_manifest(tmp_path / "m.json", [video])
    source = FakeSource({"z.zip": {"clip.mp4": b"v", "clip.txt": b"new"}})

    report, client, _ = _run(tmp_path, source)

    assert report["skipped"] == ["2026-01-01/clip.txt"]
    assert report["uploaded"] == []
    assert client.uploads == []


def test_force_reuploads_existing_metadata(tmp_path):
    video = _video("2026-01-01/clip.mp4", "clip.mp4", "z.zip")
    video["metadata"] = {"txt": f"{BASE}/old.txt"}
    _write_manifest(tmp_path / "m.json", [video])
    source = FakeSource({"z.zip": {"clip.mp4": b"v", "clip.txt": b"new"}})

    report, client, _ = _run(tmp_path, source, force=True)

    assert report["uploaded"] == ["2026-01-01/clip.txt"]
    assert [key for key, _ in client.uploads] == ["2026-01-01/clip.txt"]


def test_dry_run_uploads_and_publishes_nothing(tmp_path):
    _write_manifest(tmp_path / "m.json",
                    [_video("2026-01-01/clip.mp4", "clip.mp4", "z.zip")])
    source = FakeSource({"z.zip": {"clip.mp4": b"v", "clip.txt": b"t"}})
    before = (tmp_path / "m.json").read_text()

    report, client, publisher = _run(tmp_path, source, dry_run=True)

    assert report["dry_run"] is True
    assert report["uploaded"] == []
    assert report["planned"] == ["2026-01-01/clip.txt"]
    assert client.uploads == []
    assert publisher.published == []
    assert (tmp_path / "m.json").read_text() == before


def test_one_failed_zip_does_not_abort_others(tmp_path):
    _write_manifest(tmp_path / "m.json", [
        _video("2026-01-01/a.mp4", "a.mp4", "bad.zip"),
        _video("2026-01-01/b.mp4", "b.mp4", "good.zip"),
    ])

    class FailingSource(FakeSource):
        def download(self, entry, dest):
            if entry.name == "bad.zip":
                raise RuntimeError("download failed")
            return super().download(entry, dest)

    source = FailingSource({
        "bad.zip": {"a.mp4": b"v", "a.txt": b"t"},
        "good.zip": {"b.mp4": b"v", "b.txt": b"t"},
    })

    report, client, _ = _run(tmp_path, source)

    assert report["failed"] == {"bad.zip": "download failed"}
    assert report["processed"] == ["good.zip"]
    assert report["uploaded"] == ["2026-01-01/b.txt"]


def test_only_zip_filter(tmp_path):
    _write_manifest(tmp_path / "m.json", [
        _video("2026-01-01/a.mp4", "a.mp4", "one.zip"),
        _video("2026-01-01/b.mp4", "b.mp4", "two.zip"),
    ])
    source = FakeSource({
        "one.zip": {"a.mp4": b"v", "a.txt": b"t"},
        "two.zip": {"b.mp4": b"v", "b.txt": b"t"},
    })

    report, client, _ = _run(tmp_path, source, only_zip="two.zip")

    assert report["processed"] == ["two.zip"]
    assert report["uploaded"] == ["2026-01-01/b.txt"]
    assert source.downloaded == ["two.zip"]


def test_max_zips_defers_the_remainder(tmp_path):
    _write_manifest(tmp_path / "m.json", [
        _video("2026-01-01/a.mp4", "a.mp4", "one.zip"),
        _video("2026-01-01/b.mp4", "b.mp4", "two.zip"),
    ])
    source = FakeSource({
        "one.zip": {"a.mp4": b"v", "a.txt": b"t"},
        "two.zip": {"b.mp4": b"v", "b.txt": b"t"},
    })

    report, _, _ = _run(tmp_path, source, max_zips=1)

    assert report["processed"] == ["one.zip"]
    assert report["deferred"] == ["two.zip"]


def test_update_manifest_false_skips_save_and_publish(tmp_path):
    _write_manifest(tmp_path / "m.json",
                    [_video("2026-01-01/clip.mp4", "clip.mp4", "z.zip")])
    source = FakeSource({"z.zip": {"clip.mp4": b"v", "clip.txt": b"t"}})
    before = (tmp_path / "m.json").read_text()

    report, client, publisher = _run(tmp_path, source, update_manifest=False)

    assert report["uploaded"] == ["2026-01-01/clip.txt"]
    assert client.uploads
    assert publisher.published == []
    assert (tmp_path / "m.json").read_text() == before


def test_matches_video_without_source_zip_by_unique_stem(tmp_path):
    _write_manifest(tmp_path / "m.json", [
        _video("2026-01-01/a.mp4", "a.mp4", "z.zip"),
        _video("2026-01-01/orphan.mp4", "orphan.mp4", None),
    ])
    source = FakeSource({"z.zip": {"a.mp4": b"v", "orphan.txt": b"t"}})

    report, _, _ = _run(tmp_path, source)

    assert report["uploaded"] == ["2026-01-01/orphan.txt"]
    video = _videos_of(tmp_path / "m.json")["2026-01-01/orphan.mp4"]
    assert video["metadata"]["txt"] == f"{BASE}/2026-01-01/orphan.txt"


def test_ambiguous_source_zip_less_stem_is_reported(tmp_path):
    _write_manifest_days(tmp_path / "m.json", {
        "2026-01-01": [
            _video("2026-01-01/a.mp4", "a.mp4", "z.zip"),
            _video("2026-01-01/orphan.mp4", "orphan.mp4", None),
        ],
        "2026-01-02": [_video("2026-01-02/orphan.mp4", "orphan.mp4", None)],
    })
    source = FakeSource({"z.zip": {"a.mp4": b"v", "orphan.txt": b"t"}})

    report, client, _ = _run(tmp_path, source)

    assert client.uploads == []
    assert report["unmatched"] == [
        {"zip": "z.zip", "sidecar": "orphan.txt", "reason": "ambiguous stem"}]
