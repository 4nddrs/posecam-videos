from datetime import datetime, timezone

from ingest.adapters.drive import DriveZipSource


class FakeFilesList:
    def __init__(self, page):
        self._page = page

    def execute(self):
        return self._page


class FakeFiles:
    def __init__(self, pages):
        self._pages = pages
        self._index = 0
        self.captured_queries = []
        self.get_media_calls = []

    def list(self, q, fields, pageSize, pageToken=None):
        self.captured_queries.append(q)
        page = self._pages[self._index]
        self._index += 1
        return FakeFilesList(page)

    def get_media(self, fileId):
        self.get_media_calls.append(fileId)
        return ("request-for", fileId)


class FakeService:
    def __init__(self, pages):
        self._files = FakeFiles(pages)

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
    pages = [{"files": []}]
    service = FakeService(pages)
    source = DriveZipSource(service, folder_id="folder-abc")

    source.list_zips()

    assert "folder-abc" in service.files().captured_queries[0]


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
