import zipfile

from ingest.unzip import extract_videos


def _build_zip(path):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("clip1.mp4", b"fake-mp4-bytes")
        zf.writestr("clip2.MOV", b"fake-mov-bytes")
        zf.writestr("notes.txt", b"ignore me")
        zf.writestr("../evil.mp4", b"traversal-attempt")
    return path


def test_extract_videos_filters_extensions_and_skips_traversal(tmp_path):
    zip_path = _build_zip(tmp_path / "recordings.zip")
    dest_dir = tmp_path / "out"

    videos = extract_videos(zip_path, dest_dir)

    names = sorted(p.name for p in videos)
    assert names == ["clip1.mp4", "clip2.MOV"]
    for video in videos:
        assert video.exists()
    assert not (dest_dir / ".." / "evil.mp4").resolve().exists()
    # traversal entry must never land anywhere under dest_dir's parent
    assert not (tmp_path / "evil.mp4").exists()


def test_extract_videos_rejects_absolute_path_entries(tmp_path):
    zip_path = tmp_path / "absolute.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("/etc/evil.mp4", b"absolute-path-attempt")
        zf.writestr("good.mp4", b"real video")

    dest_dir = tmp_path / "out2"
    videos = extract_videos(zip_path, dest_dir)

    names = sorted(p.name for p in videos)
    assert names == ["good.mp4"]
    assert not (dest_dir / "etc" / "evil.mp4").exists()
