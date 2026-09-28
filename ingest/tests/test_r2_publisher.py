from pathlib import Path

from ingest.adapters.r2 import R2VideoPublisher


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
