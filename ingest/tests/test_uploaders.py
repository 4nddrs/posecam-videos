import json

from ingest.adapters.drive import DriveZipSource
from ingest.tests.test_drive_source import FakeService
from ingest.uploaders import backfill_uploaders


def _drive(files):
    folders = {"root": [{"id": "f1", "name": "Remaining Videos"}]}
    pages = {"root": [{"files": []}], "f1": [{"files": files}]}
    return DriveZipSource(FakeService(pages, folders), "root", category="Mix")


def _file(fid, name, owner):
    return {
        "id": fid,
        "name": name,
        "createdTime": "2026-09-29T01:00:00Z",
        "mimeType": "application/zip",
        "owners": [{"displayName": owner, "emailAddress": "secret@example.com"}],
    }


def _manifest(tmp_path, videos):
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"generated_at": "t", "days": [{"day": "2026-09-27", "videos": videos}]}))
    return path


def test_backfill_matches_source_zip_ignoring_copy_counters(tmp_path):
    path = _manifest(
        tmp_path,
        [
            {"id": "a", "name": "a.mp4", "source_zip": "capture-1-pipeline.zip"},
            {"id": "b", "name": "b.mp4", "source_zip": "capture-2-pipeline (1).zip"},
            {"id": "c", "name": "c.mp4", "source_zip": "unknown.zip"},
        ],
    )
    source = _drive(
        [_file("1", "capture-1-pipeline.zip", "Ann"), _file("2", "capture-2-pipeline.zip", "Bob")]
    )

    report = backfill_uploaders(path, source)

    videos = {v["id"]: v for v in json.loads(path.read_text())["days"][0]["videos"]}
    assert videos["a"]["uploader"] == "Ann"
    assert videos["b"]["uploader"] == "Bob"
    assert videos["c"]["uploader"] is None
    assert report == {"videos": 3, "uploader_filled": 2, "uploader_unmatched": 1, "category_set": 3}


def test_backfill_sets_missing_category_keeps_existing_and_never_writes_emails(tmp_path):
    path = _manifest(
        tmp_path,
        [
            {"id": "a", "name": "a.mp4", "source_zip": "x.zip"},
            {"id": "b", "name": "b.mp4", "source_zip": "x.zip", "category": "White pipes", "uploader": "Kept"},
        ],
    )

    backfill_uploaders(path, _drive([_file("1", "x.zip", "Ann")]))

    text = path.read_text()
    videos = {v["id"]: v for v in json.loads(text)["days"][0]["videos"]}
    assert videos["a"]["category"] == "Mix"
    assert videos["b"]["category"] == "White pipes"
    assert videos["b"]["uploader"] == "Kept"
    assert "@" not in text
    assert json.loads(text)["generated_at"] == "t"


def test_backfill_is_idempotent(tmp_path):
    path = _manifest(tmp_path, [{"id": "a", "name": "a.mp4", "source_zip": "x.zip"}])
    backfill_uploaders(path, _drive([_file("1", "x.zip", "Ann")]))
    first = path.read_text()
    report = backfill_uploaders(path, _drive([_file("1", "x.zip", "Ann")]))

    assert path.read_text() == first
    assert report["uploader_filled"] == 0
