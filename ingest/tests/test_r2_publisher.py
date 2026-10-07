import sys
import types
from pathlib import Path

from ingest.adapters.r2 import R2VideoPublisher, build_r2_publisher


class FakeClient:
    def __init__(self) -> None:
        self.upload_file_calls = []

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        self.upload_file_calls.append(
            {"filename": filename, "bucket": bucket, "key": key, "ExtraArgs": ExtraArgs}
        )


def test_publish_uploads_with_guessed_content_type_and_day_prefixed_key(tmp_path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"fake video bytes")
    client = FakeClient()
    publisher = R2VideoPublisher(client, bucket="my-bucket", public_base_url="https://videos.example.com")

    published = publisher.publish(video_path, day="2026-09-01")

    assert len(client.upload_file_calls) == 1
    call = client.upload_file_calls[0]
    assert call["filename"] == str(video_path)
    assert call["bucket"] == "my-bucket"
    assert call["key"] == "2026-09-01/clip.mp4"
    assert call["ExtraArgs"] == {"ContentType": "video/mp4"}

    assert published.id == "2026-09-01/clip.mp4"
    assert published.name == "clip.mp4"
    assert published.url == "https://videos.example.com/2026-09-01/clip.mp4"


def test_publish_defaults_to_octet_stream_for_unknown_extension(tmp_path):
    video_path = tmp_path / "clip.unknownext"
    video_path.write_bytes(b"data")
    client = FakeClient()
    publisher = R2VideoPublisher(client, bucket="bucket", public_base_url="https://videos.example.com")

    publisher.publish(video_path, day="2026-09-02")

    call = client.upload_file_calls[0]
    assert call["ExtraArgs"] == {"ContentType": "application/octet-stream"}


def test_publish_url_encodes_spaces_in_the_key(tmp_path):
    video_path = tmp_path / "my clip.mp4"
    video_path.write_bytes(b"data")
    client = FakeClient()
    publisher = R2VideoPublisher(client, bucket="bucket", public_base_url="https://videos.example.com")

    published = publisher.publish(video_path, day="2026-09-03")

    assert published.id == "2026-09-03/my clip.mp4"
    assert published.url == "https://videos.example.com/2026-09-03/my%20clip.mp4"


def test_publish_strips_trailing_slash_from_public_base_url(tmp_path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"data")
    client = FakeClient()
    publisher = R2VideoPublisher(client, bucket="bucket", public_base_url="https://videos.example.com/")

    published = publisher.publish(video_path, day="2026-09-04")

    assert published.url == "https://videos.example.com/2026-09-04/clip.mp4"


def _fake_boto3(monkeypatch):
    calls = []
    module = types.SimpleNamespace(client=lambda *a, **kw: calls.append((a, kw)) or FakeClient())
    monkeypatch.setitem(sys.modules, "boto3", module)
    return calls


def test_build_r2_publisher_derives_default_endpoint(monkeypatch):
    calls = _fake_boto3(monkeypatch)

    build_r2_publisher("acc", "kid", "secret", "bucket", "https://v.example.com")

    assert calls[0][1]["endpoint_url"] == "https://acc.r2.cloudflarestorage.com"


def test_build_r2_publisher_uses_explicit_endpoint(monkeypatch):
    calls = _fake_boto3(monkeypatch)

    build_r2_publisher(
        "acc", "kid", "secret", "bucket", "https://v.example.com",
        endpoint_url="https://custom.example.com",
    )

    assert calls[0][1]["endpoint_url"] == "https://custom.example.com"


def test_publish_uploads_poster_as_jpeg(tmp_path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"v")
    poster = tmp_path / "poster.jpg"
    poster.write_bytes(b"p")
    client = FakeClient()
    publisher = R2VideoPublisher(client, bucket="b", public_base_url="https://cdn.example.com")

    published = publisher.publish(video_path, day="2026-09-01", poster_path=poster)

    keys = [c["key"] for c in client.upload_file_calls]
    assert keys == ["2026-09-01/clip.mp4", "2026-09-01/clip.jpg"]
    assert client.upload_file_calls[1]["ExtraArgs"] == {"ContentType": "image/jpeg"}
    assert published.poster_url == "https://cdn.example.com/2026-09-01/clip.jpg"


def test_publish_without_poster_has_no_poster_url(tmp_path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"v")
    publisher = R2VideoPublisher(FakeClient(), bucket="b", public_base_url="https://cdn.example.com")
    assert publisher.publish(video_path, day="d").poster_url is None


def test_publish_sidecar_uploads_txt_with_plain_content_type(tmp_path):
    session = "2026-10-07-04_27_08-1cc1cb-s1"
    sidecar = tmp_path / f"AR_Pose_{session}.txt"
    sidecar.write_bytes(b"pose data")
    client = FakeClient()
    publisher = R2VideoPublisher(client, bucket="my-bucket", public_base_url="https://videos.example.com")

    url = publisher.publish_sidecar(sidecar, day="2026-10-07", session=session)

    assert client.upload_file_calls == [{
        "filename": str(sidecar),
        "bucket": "my-bucket",
        "key": f"2026-10-07/{session}/AR_Pose_{session}.txt",
        "ExtraArgs": {"ContentType": "text/plain; charset=utf-8"},
    }]
    assert url == f"https://videos.example.com/2026-10-07/{session}/AR_Pose_{session}.txt"


def test_publish_sidecar_uploads_json_with_json_content_type(tmp_path):
    session = "2026-10-07-04_27_08-1cc1cb-s1"
    sidecar = tmp_path / "posecam_export.json"
    sidecar.write_bytes(b"{}")
    client = FakeClient()
    publisher = R2VideoPublisher(client, bucket="my-bucket", public_base_url="https://videos.example.com")

    url = publisher.publish_sidecar(sidecar, day="2026-10-07", session=session)

    assert client.upload_file_calls == [{
        "filename": str(sidecar),
        "bucket": "my-bucket",
        "key": f"2026-10-07/{session}/posecam_export.json",
        "ExtraArgs": {"ContentType": "application/json"},
    }]
    assert url == f"https://videos.example.com/2026-10-07/{session}/posecam_export.json"


def test_publish_sidecar_url_encodes_spaces_in_the_key(tmp_path):
    sidecar = tmp_path / "a sidecar.txt"
    sidecar.write_bytes(b"data")
    client = FakeClient()
    publisher = R2VideoPublisher(client, bucket="bucket", public_base_url="https://videos.example.com")

    url = publisher.publish_sidecar(sidecar, day="2026-09-03", session="s1")

    assert url == "https://videos.example.com/2026-09-03/s1/a%20sidecar.txt"


def test_publish_manifest_uploads_to_bucket_root_without_cache(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    client = FakeClient()
    publisher = R2VideoPublisher(client, bucket="b", public_base_url="https://cdn.example.com/")

    url = publisher.publish_manifest(manifest)

    assert client.upload_file_calls == [{
        "filename": str(manifest),
        "bucket": "b",
        "key": "manifest.json",
        "ExtraArgs": {"ContentType": "application/json", "CacheControl": "no-cache"},
    }]
    assert url == "https://cdn.example.com/manifest.json"
