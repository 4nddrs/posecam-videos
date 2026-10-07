import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from ingest.ports import ZipEntry
from ingest.sidecars import run_sidecars

BASE = "https://cdn.example.com"

ZIP = "z.zip"
SESSION = "2026-01-01-08_00_00-abc123-s1"
DAY = "2026-01-01"
VIDEO_NAME = f"RGB_{SESSION}.mp4"
VIDEO_ID = f"{DAY}/{VIDEO_NAME}"
POSE_NAME = f"AR_Pose_{SESSION}.txt"
EXPORT_NAME = "posecam_export.json"


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


def _members(session, *, video=False, pose=False, export=False, prefix="capture-x"):
    """Build the real per-session zip layout: `<prefix>/<session>/<file>`."""
    folder = f"{prefix}/{session}"
    members = {}
    if video:
        members[f"{folder}/RGB_{session}.mp4"] = b"v"
    if pose:
        members[f"{folder}/AR_Pose_{session}.txt"] = b"t"
    if export:
        members[f"{folder}/{EXPORT_NAME}"] = b"{}"
    return members


def _key(session, filename, day=DAY):
    return f"{day}/{session}/{filename}"


def _write_manifest(path, videos, day=DAY):
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


def test_pairs_sidecars_by_session_folder_and_records_metadata(tmp_path):
    _write_manifest(tmp_path / "m.json", [_video(VIDEO_ID, VIDEO_NAME, ZIP)])
    source = FakeSource({ZIP: _members(SESSION, video=True, pose=True, export=True)})

    report, client, publisher = _run(tmp_path, source)

    assert report["processed"] == [ZIP]
    assert sorted(key for key, _ in client.uploads) == sorted([
        _key(SESSION, EXPORT_NAME), _key(SESSION, POSE_NAME)])
    assert report["missing"] == []
    assert report["unmatched"] == []
    assert publisher.published == [tmp_path / "m.json"]

    video = _videos_of(tmp_path / "m.json")[VIDEO_ID]
    assert video["metadata"]["txt"] == f"{BASE}/{_key(SESSION, POSE_NAME)}"
    assert video["metadata"]["json"] == f"{BASE}/{_key(SESSION, EXPORT_NAME)}"


def test_uploads_correct_content_types(tmp_path):
    _write_manifest(tmp_path / "m.json", [_video(VIDEO_ID, VIDEO_NAME, ZIP)])
    source = FakeSource({ZIP: _members(SESSION, video=True, pose=True, export=True)})

    _, client, _ = _run(tmp_path, source)

    types = {key: extra["ContentType"] for key, extra in client.uploads}
    assert types[_key(SESSION, POSE_NAME)] == "text/plain; charset=utf-8"
    assert types[_key(SESSION, EXPORT_NAME)] == "application/json"


def test_two_sessions_in_one_zip_do_not_collide(tmp_path):
    s1 = SESSION
    s2 = "2026-01-01-09_00_00-def456-s1"
    _write_manifest(tmp_path / "m.json", [
        _video(f"{DAY}/RGB_{s1}.mp4", f"RGB_{s1}.mp4", ZIP),
        _video(f"{DAY}/RGB_{s2}.mp4", f"RGB_{s2}.mp4", ZIP),
    ])
    members = {}
    members.update(_members(s1, video=True, pose=True, export=True))
    members.update(_members(s2, video=True, pose=True, export=True))

    report, _, _ = _run(tmp_path, FakeSource({ZIP: members}))

    assert sorted(report["uploaded"]) == sorted([
        _key(s1, EXPORT_NAME), _key(s1, POSE_NAME),
        _key(s2, EXPORT_NAME), _key(s2, f"AR_Pose_{s2}.txt")])

    videos = _videos_of(tmp_path / "m.json")
    assert videos[f"{DAY}/RGB_{s1}.mp4"]["metadata"]["txt"] == f"{BASE}/{_key(s1, POSE_NAME)}"
    assert videos[f"{DAY}/RGB_{s2}.mp4"]["metadata"]["txt"] == f"{BASE}/{_key(s2, f'AR_Pose_{s2}.txt')}"


def test_unmatched_sidecar_without_session_folder_is_reported(tmp_path):
    _write_manifest(tmp_path / "m.json", [_video(VIDEO_ID, VIDEO_NAME, ZIP)])
    source = FakeSource({ZIP: {**_members(SESSION, video=True), "orphan.txt": b"x"}})

    report, client, _ = _run(tmp_path, source)

    assert client.uploads == []
    assert report["unmatched"] == [
        {"zip": ZIP, "sidecar": "orphan.txt", "reason": "no session folder"}]


def test_unmatched_sidecar_with_no_matching_video_is_reported(tmp_path):
    other = "2026-02-02-10_00_00-999999-s1"
    _write_manifest(tmp_path / "m.json", [_video(VIDEO_ID, VIDEO_NAME, ZIP)])
    source = FakeSource({ZIP: {
        **_members(SESSION, video=True),
        **_members(other, pose=True),
    }})

    report, client, _ = _run(tmp_path, source)

    assert client.uploads == []
    assert report["unmatched"] == [
        {"zip": ZIP, "sidecar": f"AR_Pose_{other}.txt", "reason": "no matching video"}]


def test_ambiguous_session_is_reported(tmp_path):
    dup = "2026-03-03-11_00_00-777777-s1"
    _write_manifest_days(tmp_path / "m.json", {
        DAY: [_video(VIDEO_ID, VIDEO_NAME, ZIP)],
        "2026-01-02": [_video(f"2026-01-02/RGB_{dup}.mp4", f"RGB_{dup}.mp4", None)],
        "2026-01-03": [_video(f"2026-01-03/RGB_{dup}.mp4", f"RGB_{dup}.mp4", None)],
    })
    source = FakeSource({ZIP: {
        **_members(SESSION, video=True),
        **_members(dup, pose=True),
    }})

    report, client, _ = _run(tmp_path, source)

    assert client.uploads == []
    assert report["unmatched"] == [
        {"zip": ZIP, "sidecar": f"AR_Pose_{dup}.txt", "reason": "ambiguous session"}]


def test_matches_unique_session_token_across_manifest(tmp_path):
    orphan = "2026-04-04-12_00_00-abcdef-s1"
    _write_manifest(tmp_path / "m.json", [
        _video(VIDEO_ID, VIDEO_NAME, ZIP),
        _video(f"{DAY}/RGB_{orphan}.mp4", f"RGB_{orphan}.mp4", None),
    ])
    source = FakeSource({ZIP: {
        **_members(SESSION, video=True),
        **_members(orphan, pose=True),
    }})

    report, _, _ = _run(tmp_path, source)

    assert report["uploaded"] == [_key(orphan, f"AR_Pose_{orphan}.txt")]
    video = _videos_of(tmp_path / "m.json")[f"{DAY}/RGB_{orphan}.mp4"]
    assert video["metadata"]["txt"] == f"{BASE}/{_key(orphan, f'AR_Pose_{orphan}.txt')}"


def test_ambiguous_sidecar_is_reported(tmp_path):
    folder = f"capture-x/{SESSION}"
    _write_manifest(tmp_path / "m.json", [_video(VIDEO_ID, VIDEO_NAME, ZIP)])
    source = FakeSource({ZIP: {
        f"{folder}/RGB_{SESSION}.mp4": b"v",
        f"{folder}/{POSE_NAME}": b"t",
        f"{folder}/other.txt": b"t2",
    }})

    report, client, _ = _run(tmp_path, source)

    assert [key for key, _ in client.uploads] == [_key(SESSION, POSE_NAME)]
    assert report["unmatched"] == [
        {"zip": ZIP, "sidecar": "other.txt", "reason": "ambiguous sidecar"}]


def test_video_without_sidecar_is_missing(tmp_path):
    _write_manifest(tmp_path / "m.json", [_video(VIDEO_ID, VIDEO_NAME, ZIP)])
    source = FakeSource({ZIP: _members(SESSION, video=True)})

    report, _, _ = _run(tmp_path, source)

    assert report["missing"] == [VIDEO_ID]


def test_skips_existing_metadata_unless_forced(tmp_path):
    video = _video(VIDEO_ID, VIDEO_NAME, ZIP)
    video["metadata"] = {"txt": f"{BASE}/old.txt"}
    _write_manifest(tmp_path / "m.json", [video])
    source = FakeSource({ZIP: _members(SESSION, video=True, pose=True)})

    report, client, _ = _run(tmp_path, source)

    assert report["skipped"] == [_key(SESSION, POSE_NAME)]
    assert report["uploaded"] == []
    assert client.uploads == []


def test_force_reuploads_existing_metadata(tmp_path):
    video = _video(VIDEO_ID, VIDEO_NAME, ZIP)
    video["metadata"] = {"txt": f"{BASE}/old.txt"}
    _write_manifest(tmp_path / "m.json", [video])
    source = FakeSource({ZIP: _members(SESSION, video=True, pose=True)})

    report, client, _ = _run(tmp_path, source, force=True)

    assert report["uploaded"] == [_key(SESSION, POSE_NAME)]
    assert [key for key, _ in client.uploads] == [_key(SESSION, POSE_NAME)]


def test_dry_run_uploads_and_publishes_nothing(tmp_path):
    _write_manifest(tmp_path / "m.json", [_video(VIDEO_ID, VIDEO_NAME, ZIP)])
    source = FakeSource({ZIP: _members(SESSION, video=True, pose=True)})
    before = (tmp_path / "m.json").read_text()

    report, client, publisher = _run(tmp_path, source, dry_run=True)

    assert report["dry_run"] is True
    assert report["uploaded"] == []
    assert report["planned"] == [_key(SESSION, POSE_NAME)]
    assert client.uploads == []
    assert publisher.published == []
    assert (tmp_path / "m.json").read_text() == before


def test_one_failed_zip_does_not_abort_others(tmp_path):
    a = "2026-05-05-13_00_00-abc111-s1"
    b = "2026-05-05-14_00_00-abc222-s1"
    _write_manifest(tmp_path / "m.json", [
        _video(f"{DAY}/RGB_{a}.mp4", f"RGB_{a}.mp4", "bad.zip"),
        _video(f"{DAY}/RGB_{b}.mp4", f"RGB_{b}.mp4", "good.zip"),
    ])

    class FailingSource(FakeSource):
        def download(self, entry, dest):
            if entry.name == "bad.zip":
                raise RuntimeError("download failed")
            return super().download(entry, dest)

    source = FailingSource({
        "bad.zip": _members(a, video=True, pose=True),
        "good.zip": _members(b, video=True, pose=True),
    })

    report, client, _ = _run(tmp_path, source)

    assert report["failed"] == {"bad.zip": "download failed"}
    assert report["processed"] == ["good.zip"]
    assert report["uploaded"] == [_key(b, f"AR_Pose_{b}.txt")]


def test_only_zip_filter(tmp_path):
    a = "2026-06-06-15_00_00-abc111-s1"
    b = "2026-06-06-16_00_00-abc222-s1"
    _write_manifest(tmp_path / "m.json", [
        _video(f"{DAY}/RGB_{a}.mp4", f"RGB_{a}.mp4", "one.zip"),
        _video(f"{DAY}/RGB_{b}.mp4", f"RGB_{b}.mp4", "two.zip"),
    ])
    source = FakeSource({
        "one.zip": _members(a, video=True, pose=True),
        "two.zip": _members(b, video=True, pose=True),
    })

    report, client, _ = _run(tmp_path, source, only_zip="two.zip")

    assert report["processed"] == ["two.zip"]
    assert report["uploaded"] == [_key(b, f"AR_Pose_{b}.txt")]
    assert source.downloaded == ["two.zip"]


def test_max_zips_defers_the_remainder(tmp_path):
    a = "2026-07-07-17_00_00-abc111-s1"
    b = "2026-07-07-18_00_00-abc222-s1"
    _write_manifest(tmp_path / "m.json", [
        _video(f"{DAY}/RGB_{a}.mp4", f"RGB_{a}.mp4", "one.zip"),
        _video(f"{DAY}/RGB_{b}.mp4", f"RGB_{b}.mp4", "two.zip"),
    ])
    source = FakeSource({
        "one.zip": _members(a, video=True, pose=True),
        "two.zip": _members(b, video=True, pose=True),
    })

    report, _, _ = _run(tmp_path, source, max_zips=1)

    assert report["processed"] == ["one.zip"]
    assert report["deferred"] == ["two.zip"]


def test_update_manifest_false_skips_save_and_publish(tmp_path):
    _write_manifest(tmp_path / "m.json", [_video(VIDEO_ID, VIDEO_NAME, ZIP)])
    source = FakeSource({ZIP: _members(SESSION, video=True, pose=True)})
    before = (tmp_path / "m.json").read_text()

    report, client, publisher = _run(tmp_path, source, update_manifest=False)

    assert report["uploaded"] == [_key(SESSION, POSE_NAME)]
    assert client.uploads
    assert publisher.published == []
    assert (tmp_path / "m.json").read_text() == before
