import json

from ingest.manifest import Manifest, load, save
from ingest.ports import PublishedVideo


def test_manifest_groups_sorts_and_serializes():
    manifest = Manifest()
    manifest.add(
        "2026-09-27",
        "zip-a.zip",
        PublishedVideo(id="v2", name="b.mp4", url="https://example.com/b.mp4"),
    )
    manifest.add(
        "2026-09-28",
        "zip-b.zip",
        PublishedVideo(id="v1", name="a.mp4", url="https://example.com/a.mp4"),
    )
    manifest.add(
        "2026-09-27",
        "zip-a.zip",
        PublishedVideo(id="v3", name="a.mp4", url="https://example.com/a2.mp4"),
    )

    data = manifest.to_dict()

    assert "generated_at" in data
    days = data["days"]
    assert [d["day"] for d in days] == ["2026-09-28", "2026-09-27"]

    day_27 = next(d for d in days if d["day"] == "2026-09-27")
    assert [v["name"] for v in day_27["videos"]] == ["a.mp4", "b.mp4"]
    assert day_27["videos"][0] == {
        "id": "v3",
        "name": "a.mp4",
        "url": "https://example.com/a2.mp4",
        "source_zip": "zip-a.zip",
    }


def test_save_and_load_merge_without_duplicates(tmp_path):
    path = tmp_path / "manifest.json"

    first = Manifest()
    first.add(
        "2026-09-27",
        "zip-a.zip",
        PublishedVideo(id="v1", name="a.mp4", url="https://example.com/a.mp4"),
    )
    save(first, path)

    reloaded = load(path)
    reloaded.add(
        "2026-09-28",
        "zip-b.zip",
        PublishedVideo(id="v2", name="b.mp4", url="https://example.com/b.mp4"),
    )
    # duplicate id for an already-recorded video on the same day must not duplicate
    reloaded.add(
        "2026-09-27",
        "zip-a.zip",
        PublishedVideo(id="v1", name="a.mp4", url="https://example.com/a.mp4"),
    )
    save(reloaded, path)

    final = load(path)
    data = final.to_dict()
    assert [d["day"] for d in data["days"]] == ["2026-09-28", "2026-09-27"]
    day_27 = next(d for d in data["days"] if d["day"] == "2026-09-27")
    assert len(day_27["videos"]) == 1

    raw = json.loads(path.read_text())
    assert raw["days"][0]["day"] == "2026-09-28"
