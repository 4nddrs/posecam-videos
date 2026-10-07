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
        self.manifests = []
        self.sidecars = []
        self._fail_for_names = fail_for_names or set()

    def publish_manifest(self, manifest_path):
        self.manifests.append(Path(manifest_path).read_text())
        return "https://cdn.example.com/manifest.json"

    def publish_sidecar(self, sidecar_path, day, session):
        self.sidecars.append((sidecar_path.name, day, session))
        return f"https://cdn.example.com/{day}/{session}/{sidecar_path.name}"

    def publish(self, video_path, day, poster_path=None):
        self.posters = getattr(self, 'posters', []) + [poster_path]
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


def _make_session_zip_bytes(tmp_path, name, session, with_sidecars=True):
    """Build a zip shaped like a real recording: <stem>/<session>/{video,sidecars}."""
    zip_path = tmp_path / name
    stem = Path(name).stem
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(f"{stem}/{session}/RGB_{session}.mp4", b"fake-video-bytes")
        if with_sidecars:
            zf.writestr(f"{stem}/{session}/AR_Pose_{session}.txt", b"pose")
            zf.writestr(f"{stem}/{session}/posecam_export.json", b"{}")
    data = zip_path.read_bytes()
    zip_path.unlink()
    return data


def test_run_ingest_publishes_sidecars_and_records_metadata(tmp_path):
    session = "2026-10-07-04_27_08-1cc1cb-s1"
    entry = _entry("z1", "drain.zip", day="2026-10-07")
    source = FakeZipSource([entry], {"z1": _make_session_zip_bytes(tmp_path, "drain.zip", session)})
    publisher = FakePublisher()

    report = run_ingest(source, publisher, FakeStateStore(), tmp_path / "m.json", tmp_path / "w")

    assert report.processed == ["z1"]
    assert sorted(publisher.sidecars) == [
        ("AR_Pose_2026-10-07-04_27_08-1cc1cb-s1.txt", "2026-10-07", session),
        ("posecam_export.json", "2026-10-07", session),
    ]
    video = load(tmp_path / "m.json").to_dict()["days"][0]["videos"][0]
    assert video["metadata"] == {
        "txt": f"https://cdn.example.com/2026-10-07/{session}/AR_Pose_{session}.txt",
        "json": f"https://cdn.example.com/2026-10-07/{session}/posecam_export.json",
    }


def test_run_ingest_video_only_zip_has_no_metadata_and_no_sidecar_publish(tmp_path):
    session = "2026-10-07-04_27_08-1cc1cb-s1"
    entry = _entry("z1", "drain.zip", day="2026-10-07")
    source = FakeZipSource(
        [entry], {"z1": _make_session_zip_bytes(tmp_path, "drain.zip", session, with_sidecars=False)}
    )
    publisher = FakePublisher()

    run_ingest(source, publisher, FakeStateStore(), tmp_path / "m.json", tmp_path / "w")

    assert publisher.sidecars == []
    video = load(tmp_path / "m.json").to_dict()["days"][0]["videos"][0]
    assert "metadata" not in video


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


def test_run_ingest_publishes_processed_video_with_poster(tmp_path):
    from datetime import datetime, timezone
    from ingest.ports import ProcessedVideo, ZipEntry

    entry = ZipEntry(id="z1", name="z1.zip", uploaded_at=datetime(2026, 9, 1, tzinfo=timezone.utc), day="2026-09-01")
    source = FakeZipSource([entry], {"z1": _make_zip_bytes(tmp_path, "z1.zip", ["a.mp4"])})
    publisher = FakePublisher()
    seen = []

    class Proc:
        def process(self, video_path, workdir):
            seen.append(video_path.name)
            return ProcessedVideo(video_path=video_path, poster_path=workdir / "a.jpg")

    run_ingest(source, publisher, FakeStateStore(), tmp_path / "m.json", tmp_path / "w", processor=Proc())
    assert seen == ["a.mp4"]
    assert publisher.posters[0].name == "a.jpg"


def test_run_ingest_attaches_duration_to_manifest(tmp_path):
    from ingest.ports import ProcessedVideo

    entry = ZipEntry(id="z1", name="z1.zip", uploaded_at=datetime(2026, 9, 1, tzinfo=timezone.utc), day="2026-09-01")
    source = FakeZipSource([entry], {"z1": _make_zip_bytes(tmp_path, "z1.zip", ["a.mp4"])})

    class Proc:
        def process(self, video_path, workdir):
            return ProcessedVideo(video_path=video_path, poster_path=None, duration_seconds=42.5)

    run_ingest(source, FakePublisher(), FakeStateStore(), tmp_path / "m.json", tmp_path / "w", processor=Proc())
    videos = load(tmp_path / "m.json").to_dict()["days"][0]["videos"]
    assert videos[0]["duration"] == 42.5


def test_run_ingest_records_category_and_uploader_in_manifest(tmp_path):
    entry = ZipEntry(
        id="z1", name="z1.zip", uploaded_at=datetime(2026, 9, 30, tzinfo=timezone.utc),
        day="2026-09-30", category="Black pipes", uploader="Arshil Bhingradiya",
    )
    source = FakeZipSource([entry], {"z1": _make_zip_bytes(tmp_path, "z1.zip", ["a.mp4"])})

    run_ingest(source, FakePublisher(), FakeStateStore(), tmp_path / "m.json", tmp_path / "w")

    video = load(tmp_path / "m.json").to_dict()["days"][0]["videos"][0]
    assert video["category"] == "Black Pipes"
    assert video["uploader"] == "Arshil Bhingradiya"


def test_run_ingest_publishes_manifest_once_after_all_zips(tmp_path):
    uploaded_at = datetime(2026, 9, 27, 10, 0, tzinfo=timezone.utc)
    entries = [
        ZipEntry(id="zip-1", name="a.zip", uploaded_at=uploaded_at),
        ZipEntry(id="zip-2", name="b.zip", uploaded_at=uploaded_at),
    ]
    zips = {
        "zip-1": _make_zip_bytes(tmp_path, "a.zip", ["a.mp4"]),
        "zip-2": _make_zip_bytes(tmp_path, "b.zip", ["b.mp4"]),
    }
    publisher = FakePublisher()

    run_ingest(
        FakeZipSource(entries, zips), publisher, FakeStateStore(),
        tmp_path / "manifest.json", tmp_path / "work",
    )

    assert len(publisher.manifests) == 1
    assert "b.mp4" in publisher.manifests[0]


def test_run_ingest_does_not_publish_manifest_when_nothing_processed(tmp_path):
    publisher = FakePublisher()

    run_ingest(
        FakeZipSource([], {}), publisher, FakeStateStore(),
        tmp_path / "manifest.json", tmp_path / "work",
    )

    assert publisher.manifests == []
