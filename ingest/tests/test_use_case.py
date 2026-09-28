import zipfile
from datetime import datetime, timezone
from pathlib import Path

from ingest.manifest import load
from ingest.ports import PublishedVideo, ZipEntry
from ingest.use_case import run_ingest


class FakeZipSource:
    def __init__(self, entries, zip_bytes_by_id):
        self._entries = entries
        self._zip_bytes_by_id = zip_bytes_by_id

    def list_zips(self):
        return self._entries

    def download(self, entry, dest):
        dest.write_bytes(self._zip_bytes_by_id[entry.id])
        return dest


class FakePublisher:
    def __init__(self, fail_for_names=None):
        self.published = []
        self._fail_for_names = fail_for_names or set()

    def publish(self, video_path, day):
        if video_path.name in self._fail_for_names:
            raise RuntimeError(f"publish failed for {video_path.name}")
        video_id = f"{day}-{video_path.name}"
        self.published.append(video_id)
        return PublishedVideo(
            id=video_id, name=video_path.name, url=f"https://cdn.example.com/{video_id}"
        )


class FakeStateStore:
    def __init__(self):
        self._processed = set()

    def processed_ids(self):
        return set(self._processed)

    def mark_processed(self, zip_id):
        self._processed.add(zip_id)


def _make_zip_bytes(tmp_path, name, video_names):
    zip_path = tmp_path / name
    with zipfile.ZipFile(zip_path, "w") as zf:
        for video_name in video_names:
            zf.writestr(video_name, b"fake-video-bytes")
    data = zip_path.read_bytes()
    zip_path.unlink()
    return data


def test_run_ingest_processes_new_zips(tmp_path):
    uploaded_at = datetime(2026, 9, 27, 10, 0, tzinfo=timezone.utc)
    entry = ZipEntry(id="zip-1", name="recordings.zip", uploaded_at=uploaded_at)
    zip_bytes = _make_zip_bytes(tmp_path, "recordings.zip", ["a.mp4", "b.mp4"])

    source = FakeZipSource([entry], {"zip-1": zip_bytes})
    publisher = FakePublisher()
    state = FakeStateStore()
    manifest_path = tmp_path / "manifest.json"
    workdir = tmp_path / "work"

    report = run_ingest(source, publisher, state, manifest_path, workdir)

    assert report.processed == ["zip-1"]
    assert report.skipped == []
    assert report.failed == {}
    assert state.processed_ids() == {"zip-1"}

    manifest = load(manifest_path)
    data = manifest.to_dict()
    assert data["days"][0]["day"] == "2026-09-27"
    assert [v["name"] for v in data["days"][0]["videos"]] == ["a.mp4", "b.mp4"]


def test_run_ingest_skips_already_processed_on_second_run(tmp_path):
    uploaded_at = datetime(2026, 9, 27, 10, 0, tzinfo=timezone.utc)
    entry = ZipEntry(id="zip-1", name="recordings.zip", uploaded_at=uploaded_at)
    zip_bytes = _make_zip_bytes(tmp_path, "recordings.zip", ["a.mp4"])

    source = FakeZipSource([entry], {"zip-1": zip_bytes})
    publisher = FakePublisher()
    state = FakeStateStore()
    manifest_path = tmp_path / "manifest.json"
    workdir = tmp_path / "work"

    first = run_ingest(source, publisher, state, manifest_path, workdir)
    second = run_ingest(source, publisher, state, manifest_path, workdir)

    assert first.processed == ["zip-1"]
    assert second.processed == []
    assert second.skipped == ["zip-1"]
    assert publisher.published == ["2026-09-27-a.mp4"]


def test_run_ingest_records_failure_without_marking_processed(tmp_path):
    uploaded_at = datetime(2026, 9, 27, 10, 0, tzinfo=timezone.utc)
    entry = ZipEntry(id="zip-1", name="broken.zip", uploaded_at=uploaded_at)
    zip_bytes = _make_zip_bytes(tmp_path, "broken.zip", ["bad.mp4"])

    source = FakeZipSource([entry], {"zip-1": zip_bytes})
    publisher = FakePublisher(fail_for_names={"bad.mp4"})
    state = FakeStateStore()
    manifest_path = tmp_path / "manifest.json"
    workdir = tmp_path / "work"

    report = run_ingest(source, publisher, state, manifest_path, workdir)

    assert report.processed == []
    assert "zip-1" in report.failed
    assert "bad.mp4" in report.failed["zip-1"] or "publish failed" in report.failed["zip-1"]
    assert state.processed_ids() == set()
    assert not manifest_path.exists() or load(manifest_path).to_dict()["days"] == []


def test_run_ingest_continues_after_a_failing_zip(tmp_path):
    uploaded_at = datetime(2026, 9, 27, 10, 0, tzinfo=timezone.utc)
    bad_entry = ZipEntry(id="zip-bad", name="broken.zip", uploaded_at=uploaded_at)
    good_entry = ZipEntry(id="zip-good", name="ok.zip", uploaded_at=uploaded_at)

    bad_bytes = _make_zip_bytes(tmp_path, "broken.zip", ["bad.mp4"])
    good_bytes = _make_zip_bytes(tmp_path, "ok.zip", ["good.mp4"])

    source = FakeZipSource(
        [bad_entry, good_entry], {"zip-bad": bad_bytes, "zip-good": good_bytes}
    )
    publisher = FakePublisher(fail_for_names={"bad.mp4"})
    state = FakeStateStore()
    manifest_path = tmp_path / "manifest.json"
    workdir = tmp_path / "work"

    report = run_ingest(source, publisher, state, manifest_path, workdir)

    assert report.processed == ["zip-good"]
    assert list(report.failed.keys()) == ["zip-bad"]
    assert state.processed_ids() == {"zip-good"}
