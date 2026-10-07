import json

from ingest.manifest import Manifest, load, normalize_category, save
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
        "duration": None,
        "category": "Black/White Pipes",
        "uploader": None,
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


def test_manifest_round_trips_duration(tmp_path):
    m = Manifest()
    m.add("2026-09-01", "z.zip", PublishedVideo(id="a", name="a.mp4", url="u", duration_seconds=7.25))
    m.add("2026-09-01", "z.zip", PublishedVideo(id="b", name="b.mp4", url="u2"))
    path = tmp_path / "m.json"
    save(m, path)
    videos = {v["id"]: v for v in load(path).to_dict()["days"][0]["videos"]}
    assert videos["a"]["duration"] == 7.25
    assert videos["b"]["duration"] is None


def test_load_tolerates_entries_without_duration(tmp_path):
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"days": [{"day": "d", "videos": [{"id": "a", "name": "a", "url": "u"}]}]}))
    assert load(path).to_dict()["days"][0]["videos"][0]["id"] == "a"


def test_manifest_records_category_and_uploader(tmp_path):
    m = Manifest()
    m.add("2026-09-30", "z", PublishedVideo(id="a", name="a.mp4", url="u"), category="White pipes", uploader="jayjagani19")
    m.add("2026-09-30", "z", PublishedVideo(id="b", name="b.mp4", url="u2"))
    path = tmp_path / "m.json"
    save(m, path)
    videos = {v["id"]: v for v in load(path).to_dict()["days"][0]["videos"]}
    assert videos["a"]["category"] == "White Pipes"
    assert videos["a"]["uploader"] == "jayjagani19"
    assert videos["b"]["category"] == "Black/White Pipes"
    assert videos["b"]["uploader"] is None


def test_from_dict_defaults_missing_category_to_remaining():
    data = {"days": [{"day": "d", "videos": [{"id": "a", "name": "a", "url": "u"}]}]}
    video = Manifest.from_dict(data).to_dict()["days"][0]["videos"][0]
    assert video["category"] == "Black/White Pipes"


def test_normalize_category_strips_trailing_date():
    assert normalize_category("Black pipes 1 Oct") == "Black Pipes"
    assert normalize_category("White pipes 1 OCt") == "White Pipes"
    assert normalize_category("Black pipes - 12 October 2026") == "Black Pipes"
    assert normalize_category("White pipes Oct 1") == "White Pipes"
    assert normalize_category("  Black pipes  ") == "Black Pipes"


def test_normalize_category_keeps_names_without_a_date():
    assert normalize_category("Black/White pipes") == "Black/White Pipes"
    assert normalize_category("Pipes batch 2") == "Pipes Batch 2"
    assert normalize_category("1 Oct") == "1 Oct"
    assert normalize_category(None) is None
    assert normalize_category("") is None


def test_normalize_category_canonicalizes_word_case():
    assert normalize_category("Black pipes") == "Black Pipes"
    assert normalize_category("black pipes") == "Black Pipes"


def test_dated_category_folders_merge_into_the_base_category(tmp_path):
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"days": [{"day": "2026-10-01", "videos": [
        {"id": "old", "name": "old.mp4", "url": "u", "category": "Black pipes 1 Oct"},
    ]}]}))
    m = Manifest()
    m.add("2026-10-01", "z", PublishedVideo(id="new", name="new.mp4", url="u2"), category="White pipes 1 Oct")
    save(m, path)
    videos = {v["id"]: v for v in load(path).to_dict()["days"][0]["videos"]}
    assert videos["old"]["category"] == "Black Pipes"
    assert videos["new"]["category"] == "White Pipes"


def test_normalize_category_keeps_words_that_only_start_like_a_month():
    assert normalize_category("Pipes Deck 1") == "Pipes Deck 1"
    assert normalize_category("Black pipes Mark 2") == "Black Pipes Mark 2"
    assert normalize_category("Line 2 Marked") == "Line 2 Marked"
    assert normalize_category("Team Junior 2") == "Team Junior 2"
    assert normalize_category("Pipes 99 Oct") == "Pipes 99 Oct"


def test_normalize_category_strips_full_and_short_month_names():
    assert normalize_category("Black pipes 3 Sept") == "Black Pipes"
    assert normalize_category("Black pipes (31 December)") == "Black Pipes"
    assert normalize_category("White pipes March 2nd") == "White Pipes"


def test_manifest_includes_metadata_when_provided(tmp_path):
    m = Manifest()
    m.add(
        "2026-10-07",
        "z.zip",
        PublishedVideo(id="a", name="a.mp4", url="u"),
        metadata={"txt": "https://cdn.example.com/d/s/a.txt"},
    )
    path = tmp_path / "m.json"
    save(m, path)

    video = load(path).to_dict()["days"][0]["videos"][0]
    assert video["metadata"] == {"txt": "https://cdn.example.com/d/s/a.txt"}


def test_manifest_omits_metadata_when_not_provided(tmp_path):
    m = Manifest()
    m.add("2026-10-07", "z.zip", PublishedVideo(id="a", name="a.mp4", url="u"))
    empty = Manifest()
    empty.add(
        "2026-10-07", "z.zip", PublishedVideo(id="b", name="b.mp4", url="u2"), metadata={}
    )
    path = tmp_path / "m.json"
    save(m, path)
    save(empty, tmp_path / "empty.json")

    assert "metadata" not in load(path).to_dict()["days"][0]["videos"][0]
    assert "metadata" not in load(tmp_path / "empty.json").to_dict()["days"][0]["videos"][0]


def test_normalize_category_ignores_blank_and_non_text_values():
    assert normalize_category("   ") is None
    assert normalize_category(7) is None
    data = {"days": [{"day": "d", "videos": [{"id": "a", "name": "a", "url": "u", "category": 7}]}]}
    video = Manifest.from_dict(data).to_dict()["days"][0]["videos"][0]
    assert video["category"] == "Black/White Pipes"
