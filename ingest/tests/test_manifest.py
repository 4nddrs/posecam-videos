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
        "poster": None,
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


def test_manifest_round_trips_poster(tmp_path):
    from ingest.manifest import Manifest, load, save
    from ingest.ports import PublishedVideo

    m = Manifest()
    m.add("2026-09-01", "z.zip", PublishedVideo(id="a", name="a.mp4", url="u", poster_url="p.jpg"))
    m.add("2026-09-01", "z.zip", PublishedVideo(id="b", name="b.mp4", url="u2"))
    path = tmp_path / "m.json"
    save(m, path)
    videos = {v["id"]: v for v in load(path).to_dict()["days"][0]["videos"]}
    assert videos["a"]["poster"] == "p.jpg"
    assert videos["b"]["poster"] is None


def test_load_tolerates_entries_without_poster(tmp_path):
    import json
    from ingest.manifest import load

    path = tmp_path / "m.json"
    path.write_text(json.dumps({"days": [{"day": "d", "videos": [{"id": "a", "name": "a", "url": "u"}]}]}))
    assert load(path).to_dict()["days"][0]["videos"][0]["id"] == "a"
