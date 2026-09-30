import re
from datetime import datetime, timezone

from ingest.adapters.drive import DriveZipSource


class FakeFilesList:
    def __init__(self, page):
        self._page = page

    def execute(self):
        return self._page


class FakeFiles:
    """Query-aware fake: `pages` maps a parent id to its zip pages, `folders`
    maps the root parent id to its subfolder listing."""

    def __init__(self, pages, folders=None):
        self._pages = {"folder-123": pages} if isinstance(pages, list) else pages
        self._folders = folders or {}
        self._index = {}
        self.captured_queries = []
        self.get_media_calls = []

    def list(self, q, fields, pageSize, pageToken=None):
        self.captured_queries.append(q)
        parent = re.match(r"'([^']+)' in parents", q).group(1)
        if "mimeType = 'application/vnd.google-apps.folder'" in q:
            return FakeFilesList({"files": self._folders.get(parent, [])})
        pages = self._pages.get(parent, [{"files": []}])
        i = self._index.get(parent, 0)
        self._index[parent] = i + 1
        return FakeFilesList(pages[i])

    def get_media(self, fileId):
        self.get_media_calls.append(fileId)
        return ("request-for", fileId)


class FakeService:
    def __init__(self, pages, folders=None):
        self._files = FakeFiles(pages, folders)

    def files(self):
        return self._files


class FakeDownloader:
    def __init__(self, fh, request):
        self.fh = fh
        self.request = request
        self._chunks = [b"hello ", b"world"]
        self._sent = 0

    def next_chunk(self):
        chunk = self._chunks[self._sent]
        self.fh.write(chunk)
        self._sent += 1
        done = self._sent >= len(self._chunks)
        return (None, done)


def make_downloader_factory():
    calls = []

    def factory(fh, request):
        downloader = FakeDownloader(fh, request)
        calls.append(downloader)
        return downloader

    return factory, calls


def test_list_zips_paginates_filters_non_zip_and_parses_dates():
    pages = [
        {
            "nextPageToken": "page-2",
            "files": [
                {"id": "1", "name": "day1.zip", "createdTime": "2026-09-01T10:00:00.000Z"},
                {"id": "2", "name": "readme.txt", "createdTime": "2026-09-01T11:00:00.000Z"},
            ],
        },
        {
            "files": [
                {"id": "3", "name": "day2.ZIP", "createdTime": "2026-09-02T09:30:00.000Z"},
            ],
        },
    ]
    service = FakeService(pages)
    source = DriveZipSource(service, folder_id="folder-123")

    entries = source.list_zips()

    assert [e.id for e in entries] == ["1", "3"]
    assert [e.name for e in entries] == ["day1.zip", "day2.ZIP"]
    assert entries[0].uploaded_at == datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
    assert entries[0].uploaded_at.tzinfo is not None
    assert entries[1].uploaded_at == datetime(2026, 9, 2, 9, 30, 0, tzinfo=timezone.utc)


def test_list_zips_query_contains_folder_id():
    service = FakeService({"folder-abc": [{"files": []}]})
    source = DriveZipSource(service, folder_id="folder-abc")

    source.list_zips()

    assert all("'folder-abc' in parents" in q for q in service.files().captured_queries)
    assert len(service.files().captured_queries) == 2


def test_download_writes_full_bytes_and_returns_path(tmp_path):
    from ingest.ports import ZipEntry

    pages = [{"files": []}]
    service = FakeService(pages)
    factory, calls = make_downloader_factory()
    source = DriveZipSource(service, folder_id="folder-123", downloader_factory=factory)

    entry = ZipEntry(id="42", name="day1.zip", uploaded_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    result = source.download(entry, tmp_path)

    expected_path = tmp_path / "day1.zip"
    assert result == expected_path
    assert expected_path.read_bytes() == b"hello world"
    assert len(calls) == 1
    assert service.files().get_media_calls == ["42"]


def test_build_drive_source_with_api_key_passes_developer_key(monkeypatch):
    import sys
    import types

    from ingest.adapters.drive import build_drive_source_with_api_key

    captured = {}

    def fake_build(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeService([])

    discovery = types.ModuleType("googleapiclient.discovery")
    discovery.build = fake_build
    package = types.ModuleType("googleapiclient")
    package.discovery = discovery
    monkeypatch.setitem(sys.modules, "googleapiclient", package)
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", discovery)

    source = build_drive_source_with_api_key("folder-1", "key-xyz")

    assert isinstance(source, DriveZipSource)
    assert captured["args"] == ("drive", "v3")
    assert captured["kwargs"] == {"developerKey": "key-xyz", "cache_discovery": False}


def test_list_zips_walks_dated_subfolders_and_parses_day():
    folders = {
        "folder-123": [
            {"id": "f1", "name": "26-09-2026"},
            {"id": "f2", "name": "misc"},
        ]
    }
    pages = {
        "folder-123": [
            {"files": [{"id": "r", "name": "root.zip", "createdTime": "2026-09-01T10:00:00Z"}]}
        ],
        "f1": [
            {
                "nextPageToken": "n",
                "files": [{"id": "a", "name": "a.zip", "createdTime": "2026-09-27T01:00:00Z"}],
            },
            {"files": [{"id": "b", "name": "b.zip", "createdTime": "2026-09-27T02:00:00Z"}]},
        ],
        "f2": [
            {"files": [{"id": "c", "name": "c.zip", "createdTime": "2026-09-27T03:00:00Z"}]}
        ],
    }
    service = FakeService(pages, folders)
    source = DriveZipSource(service, folder_id="folder-123")

    entries = source.list_zips()

    by_id = {e.id: e for e in entries}
    assert set(by_id) == {"r", "a", "b", "c"}
    assert by_id["a"].day == "2026-09-26"
    assert by_id["b"].day == "2026-09-26"
    assert by_id["c"].day is None  # unparseable folder name
    assert by_id["r"].day is None  # root-level zip
    assert all("in parents" in q for q in service.files().captured_queries)


def test_list_zips_accepts_x_zip_compressed_mime():
    service = FakeService([{"files": []}])
    source = DriveZipSource(service, folder_id="folder-123")

    source.list_zips()

    zip_queries = [q for q in service.files().captured_queries if "folder'" not in q]
    assert zip_queries and all("application/x-zip-compressed" in q for q in zip_queries)


def test_download_accepts_file_destination(tmp_path):
    from ingest.ports import ZipEntry

    factory, _ = make_downloader_factory()
    source = DriveZipSource(FakeService([{"files": []}]), "folder-123", downloader_factory=factory)
    entry = ZipEntry(id="1", name="d.zip", uploaded_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    target = tmp_path / "d.zip"

    assert source.download(entry, target) == target
    assert target.read_bytes() == b"hello world"


def test_day_from_zip_name_valid_invalid_and_missing():
    from ingest.adapters.drive import day_from_zip_name

    assert day_from_zip_name("capture-20260927T161649-e649a8-pipeline.zip") == "2026-09-27"
    assert day_from_zip_name("capture-20260928T194548-7484e9.zip") == "2026-09-28"
    assert day_from_zip_name("capture-20261340T161649-abc.zip") is None
    assert day_from_zip_name("day1.zip") is None
    assert day_from_zip_name("") is None


def test_normalize_zip_name_strips_trailing_counter():
    from ingest.adapters.drive import normalize_zip_name

    assert normalize_zip_name("foo (1).zip") == "foo.zip"
    assert normalize_zip_name("foo (12).ZIP") == "foo.ZIP"
    assert normalize_zip_name("foo.zip") == "foo.zip"
    assert normalize_zip_name("foo (a).zip") == "foo (a).zip"


def test_list_zips_uses_capture_name_day_inside_undated_folder():
    folders = {"folder-123": [{"id": "f1", "name": "Remaining Videos"}]}
    pages = {
        "folder-123": [{"files": []}],
        "f1": [
            {
                "files": [
                    {
                        "id": "a",
                        "name": "capture-20260927T161649-e649a8-pipeline.zip",
                        "createdTime": "2026-09-29T01:00:00Z",
                    }
                ]
            }
        ],
    }
    source = DriveZipSource(FakeService(pages, folders), folder_id="folder-123")

    entries = source.list_zips()

    assert [e.day for e in entries] == ["2026-09-27"]


def test_list_zips_capture_name_day_beats_dated_folder_and_folder_used_otherwise():
    folders = {"folder-123": [{"id": "f1", "name": "26-09-2026"}]}
    pages = {
        "folder-123": [{"files": []}],
        "f1": [
            {
                "files": [
                    {"id": "a", "name": "capture-20260928T194548-7484e9.zip", "createdTime": "2026-09-29T01:00:00Z"},
                    {"id": "b", "name": "plain.zip", "createdTime": "2026-09-29T02:00:00Z"},
                ]
            }
        ],
    }
    source = DriveZipSource(FakeService(pages, folders), folder_id="folder-123")

    by_id = {e.id: e for e in source.list_zips()}

    assert by_id["a"].day == "2026-09-28"
    assert by_id["b"].day == "2026-09-26"


def test_list_zips_drops_numbered_duplicates_in_favour_of_original():
    pages = [
        {
            "files": [
                {"id": "dup", "name": "capture-20260928T195259-1d7ba8-pipeline (1).zip", "createdTime": "2026-09-29T01:00:00Z"},
                {"id": "orig", "name": "capture-20260928T195259-1d7ba8-pipeline.zip", "createdTime": "2026-09-29T02:00:00Z"},
                {"id": "x1", "name": "solo (1).zip", "createdTime": "2026-09-29T03:00:00Z"},
                {"id": "x2", "name": "solo (2).zip", "createdTime": "2026-09-29T04:00:00Z"},
            ]
        }
    ]
    source = DriveZipSource(FakeService(pages), folder_id="folder-123")

    ids = [e.id for e in source.list_zips()]

    assert ids == ["orig", "x1"]


def _zip_file(fid, name, owner=None, mime="application/zip", created="2026-09-30T12:00:00Z"):
    info = {"id": fid, "name": name, "createdTime": created, "mimeType": mime}
    if owner is not None:
        info["owners"] = [{"displayName": owner, "emailAddress": "hidden@example.com"}]
    return info


def test_list_zips_accepts_extensionless_zip_by_mime_type():
    pages = [
        {
            "files": [
                _zip_file("a", "PoseCam capture-20260930T165850-d63582-pipeline"),
                _zip_file("b", "notes", mime="text/plain"),
            ]
        }
    ]
    source = DriveZipSource(FakeService(pages), folder_id="folder-123")

    entries = source.list_zips()

    assert [e.id for e in entries] == ["a"]
    assert entries[0].day == "2026-09-30"


def test_day_from_zip_name_finds_capture_anywhere_in_name():
    from ingest.adapters.drive import day_from_zip_name

    assert day_from_zip_name("PoseCam capture-20260930T165850-d63582-pipeline") == "2026-09-30"
    assert day_from_zip_name("capture-20260930T171631-666aa4-pipeline.zip") == "2026-09-30"


def test_list_zips_records_owner_display_name_only():
    pages = [{"files": [_zip_file("a", "x.zip", owner="jayjagani19"), _zip_file("b", "y.zip")]}]
    source = DriveZipSource(FakeService(pages), folder_id="folder-123")

    by_id = {e.id: e for e in source.list_zips()}

    assert by_id["a"].uploader == "jayjagani19"
    assert by_id["b"].uploader is None
    assert "emailAddress" not in repr(by_id["a"])


def test_list_zips_requests_owner_display_names_without_emails():
    service = FakeService([{"files": []}])
    fields_seen = []
    original = service.files().list

    def spy(q, fields, pageSize, pageToken=None):
        fields_seen.append(fields)
        return original(q=q, fields=fields, pageSize=pageSize, pageToken=pageToken)

    service.files().list = spy
    DriveZipSource(service, folder_id="folder-123").list_zips()

    zip_fields = [f for f in fields_seen if "createdTime" in f]
    assert zip_fields and all("owners(displayName)" in f for f in zip_fields)
    assert not any("emailAddress" in f for f in fields_seen)


def test_category_is_source_label_when_given():
    folders = {"root": [{"id": "f1", "name": "Remaining Videos"}]}
    pages = {
        "root": [{"files": [_zip_file("r", "root.zip")]}],
        "f1": [{"files": [_zip_file("a", "a.zip")]}],
    }
    source = DriveZipSource(FakeService(pages, folders), "root", category="Black/White pipes")

    assert {e.id: e.category for e in source.list_zips()} == {"r": "Black/White pipes", "a": "Black/White pipes"}


def test_category_is_subfolder_name_without_label_and_skips_dated_folders():
    folders = {"root": [{"id": "f1", "name": "White pipes"}, {"id": "f2", "name": "26-09-2026"}]}
    pages = {
        "root": [{"files": [_zip_file("r", "root.zip")]}],
        "f1": [{"files": [_zip_file("a", "a.zip")]}],
        "f2": [{"files": [_zip_file("b", "b.zip")]}],
    }
    source = DriveZipSource(FakeService(pages, folders), "root")

    assert {e.id: e.category for e in source.list_zips()} == {"r": None, "a": "White pipes", "b": None}


def test_dedupe_is_scoped_per_category():
    folders = {"root": [{"id": "w", "name": "White pipes"}, {"id": "k", "name": "Black pipes"}]}
    same = "PoseCam capture-20260930T165850-d63582-pipeline"
    pages = {
        "root": [{"files": []}],
        "w": [{"files": [_zip_file("w1", same), _zip_file("w2", same + " (1)")]}],
        "k": [{"files": [_zip_file("k1", same)]}],
    }
    source = DriveZipSource(FakeService(pages, folders), "root")

    assert sorted(e.id for e in source.list_zips()) == ["k1", "w1"]


def test_normalize_zip_name_strips_counter_on_extensionless_names():
    from ingest.adapters.drive import normalize_zip_name

    assert normalize_zip_name("PoseCam capture-1-pipeline (2)") == "PoseCam capture-1-pipeline"
