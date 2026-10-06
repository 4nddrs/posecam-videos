import zipfile

from ingest.unzip import extract_sidecars, extract_videos


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


def test_extract_sidecars_keeps_txt_and_json_case_insensitively(tmp_path):
    zip_path = tmp_path / "meta.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("notes.txt", b"text")
        zf.writestr("KEEP.JSON", b"{}")
        zf.writestr("clip.mp4", b"video")

    sidecars = extract_sidecars(zip_path, tmp_path / "out")

    assert sorted(p.name for p in sidecars) == ["KEEP.JSON", "notes.txt"]


def test_extract_sidecars_rejects_traversal_absolute_and_dir_entries(tmp_path):
    zip_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../evil.txt", b"traversal-attempt")
        zf.writestr("/etc/passwd.json", b"absolute-path-attempt")
        zf.writestr("folder/", b"")
        zf.writestr("good.txt", b"ok")

    dest_dir = tmp_path / "out"
    sidecars = extract_sidecars(zip_path, dest_dir)

    assert [p.name for p in sidecars] == ["good.txt"]
    assert not (tmp_path / "evil.txt").exists()
    assert not (dest_dir / "etc" / "passwd.json").exists()


def test_extract_sidecars_flattens_nested_paths(tmp_path):
    zip_path = tmp_path / "nested.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("a/b/c/notes.txt", b"text")
        zf.writestr("a/b/c/data.json", b"{}")

    dest_dir = tmp_path / "out"
    sidecars = extract_sidecars(zip_path, dest_dir)

    assert sorted(p.name for p in sidecars) == ["data.json", "notes.txt"]
    for sidecar in sidecars:
        assert sidecar.parent == dest_dir


def test_extract_sidecars_honors_custom_extensions(tmp_path):
    zip_path = tmp_path / "custom.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("notes.txt", b"text")
        zf.writestr("captions.srt", b"subs")

    sidecars = extract_sidecars(zip_path, tmp_path / "out", extensions={".srt"})

    assert [p.name for p in sidecars] == ["captions.srt"]
