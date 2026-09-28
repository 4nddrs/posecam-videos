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


def _entry(zid, name, day=None, hour=10):
    return ZipEntry(
        id=zid,
        name=name,
        uploaded_at=datetime(2026, 9, 27, hour, 0, tzinfo=timezone.utc),
        day=day,
    )


def test_run_ingest_uses_entry_day_when_set(tmp_path):
    entry = _entry("z1", "a.zip", day="2026-09-26")
    source = FakeZipSource([entry], {"z1": _make_zip_bytes(tmp_path, "a.zip", ["a.mp4"])})

    run_ingest(source, FakePublisher(), FakeStateStore(), tmp_path / "m.json", tmp_path / "w")

    assert load(tmp_path / "m.json").to_dict()["days"][0]["day"] == "2026-09-26"


def test_run_ingest_caps_at_max_zips_oldest_first_and_reports_deferred(tmp_path):
    entries = [
        _entry("z3", "c.zip", day="2026-09-27", hour=9),
        _entry("z2", "b.zip", day="2026-09-26", hour=12),
        _entry("z1", "a.zip", day="2026-09-26", hour=8),
    ]
    data = {
        e.id: _make_zip_bytes(tmp_path, e.name, [e.name + ".mp4"]) for e in entries
    }
    state = FakeStateStore()

    report = run_ingest(
        FakeZipSource(entries, data),
        FakePublisher(),
        state,
        tmp_path / "m.json",
        tmp_path / "w",
        max_zips=2,
    )

    assert report.processed == ["z1", "z2"]
    assert report.deferred == ["z3"]
    assert report.skipped == []
    assert state.processed_ids() == {"z1", "z2"}


def test_run_ingest_max_zips_ignores_already_processed(tmp_path):
    entries = [_entry("z1", "a.zip", day="2026-09-01"), _entry("z2", "b.zip", day="2026-09-02")]
    data = {e.id: _make_zip_bytes(tmp_path, e.name, ["v.mp4"]) for e in entries}
    state = FakeStateStore()
    state.mark_processed("z1")

    report = run_ingest(
        FakeZipSource(entries, data), FakePublisher(), state,
        tmp_path / "m.json", tmp_path / "w", max_zips=1,
    )

    assert report.skipped == ["z1"]
    assert report.processed == ["z2"]
    assert report.deferred == []


def test_run_ingest_cleans_workdir_after_success_and_failure(tmp_path):
    good = _entry("zg", "ok.zip", day="2026-09-26")
    bad = _entry("zb", "bad.zip", day="2026-09-27")
    data = {
        "zg": _make_zip_bytes(tmp_path, "ok.zip", ["good.mp4"]),
        "zb": _make_zip_bytes(tmp_path, "bad.zip", ["bad.mp4"]),
    }
    workdir = tmp_path / "work"

    report = run_ingest(
        FakeZipSource([good, bad], data),
        FakePublisher(fail_for_names={"bad.mp4"}),
        FakeStateStore(),
        tmp_path / "m.json",
        workdir,
    )

    assert report.processed == ["zg"]
    assert "zb" in report.failed
    assert list(workdir.iterdir()) == []
