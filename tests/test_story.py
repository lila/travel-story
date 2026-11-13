from pathlib import Path

from PIL import Image

from story.parser import parse_story
from story.cli import parser as cli_parser, run as run_cli
from story.photos import (
    add_photos,
    clean_photos,
    photos_in_apple_album,
    rebuild_cache,
    search_photos,
    update_photo_metadata,
)
from story.project import init_project
from story.render import STYLE, build_story
from story.site import build_site, find_site_config, load_site_config
from story.validate import check_story


def test_end_to_end(tmp_path: Path):
    root = tmp_path / "trip"
    originals = tmp_path / "originals"
    originals.mkdir()
    photo = originals / "lamar-bison.jpg"
    Image.new("RGB", (900, 600), "#8c7654").save(photo)
    root.mkdir()
    assert init_project(root)
    added, updated, skipped = add_photos(root, originals)
    assert (added, updated, skipped) == (1, 0, 0)
    result = search_photos(root, "lamar")
    assert len(result) == 1
    photo_id = result[0]["id"]
    story_file = root / "yellowstone.story"
    story_file.write_text(
        f"---\ntitle: Yellowstone\ndate: August 2026\n---\n\n# Lamar Valley\n\nBefore sunrise.\n\n@photo {photo_id}\nlayout: large\ncaption: A bison in morning light.\n",
        encoding="utf-8",
    )
    parsed = parse_story(story_file)
    assert parsed.metadata["title"] == "Yellowstone"
    assert parsed.photo_ids == [photo_id]
    output = build_story(root, story_file)
    page = (output / "index.html").read_text()
    assert "A bison in morning light." in page
    assert page.count("<h1>Yellowstone</h1>") == 1
    assert "<header><h1>Yellowstone</h1>" in page
    assert f'href="photos/{photo_id}/"' in page
    assert (output / "images" / f"{photo_id}.webp").exists()
    photo_page = (output / "photos" / photo_id / "index.html").read_text()
    assert "A bison in morning light." not in photo_page
    assert "Back to Yellowstone" in photo_page
    assert f"<dd>{photo_id}</dd>" in photo_page
    assert "Dimensions" in photo_page
    assert str(photo) not in photo_page
    assert "latitude" not in photo_page.lower()
    assert photo.exists()  # ingestion never moved or modified the original


def test_unknown_photo_renders_helpfully(tmp_path: Path):
    root = tmp_path
    init_project(root)
    story_file = root / "missing.story"
    story_file.write_text("---\ntitle: Missing\n---\n\n@photo deadbeef\n")
    output = build_story(root, story_file)
    assert "Unknown photo: deadbeef" in (output / "index.html").read_text()


def test_markdown_links_distinguish_external_and_internal(tmp_path: Path):
    root = tmp_path
    init_project(root)
    story_file = root / "links.story"
    story_file.write_text(
        "---\ntitle: Links\n---\n\n"
        "Visit [Yellowstone](https://www.nps.gov/yell/) or "
        "[continue below](#next).\n\n## Next\n",
        encoding="utf-8",
    )
    output = build_story(root, story_file)
    page = (output / "index.html").read_text()
    assert '<a href="https://www.nps.gov/yell/" rel="noopener noreferrer">Yellowstone</a>' in page
    assert '<a href="#next">continue below</a>' in page


def test_pair_layout_preserves_natural_aspect_ratio():
    assert ".photos.pair img" in STYLE
    assert "aspect-ratio" not in STYLE
    assert "object-fit:cover" not in STYLE


def test_check_cache_rebuild_clean_build_and_asset_credit(tmp_path: Path):
    root = tmp_path / "trip"
    originals = tmp_path / "originals"
    root.mkdir()
    originals.mkdir()
    photo = originals / "terraces.jpg"
    Image.new("RGB", (600, 400), "#c7a66a").save(photo)
    init_project(root)
    add_photos(root, originals)
    photo_id = search_photos(root, "terraces")[0]["id"]
    story_file = root / "mammoth.story"
    story_file.write_text(
        f"---\ntitle: Mammoth\n---\n\n@photo {photo_id}\nlayout: standard\n"
        "caption: Story-specific words.\n",
        encoding="utf-8",
    )

    assert check_story(root, story_file) == []
    preview = root / ".story" / "cache" / "previews" / f"{photo_id}.webp"
    thumbnail = root / ".story" / "cache" / "thumbnails" / f"{photo_id}.webp"
    preview.unlink()
    thumbnail.unlink()
    assert any("Preview cache is missing" in issue.message for issue in check_story(root, story_file))
    assert rebuild_cache(root, [photo_id[:6]]) == (1, 0, 0)
    assert preview.exists() and thumbnail.exists()

    update_photo_metadata(
        root,
        photo_id[:6],
        credit="NPS / Photographer",
        source_url="https://example.com/photo",
    )
    output = build_story(root, story_file)
    stale = output / "obsolete.txt"
    stale.write_text("old build")
    output = build_story(root, story_file)
    assert not stale.exists()
    photo_page = (output / "photos" / photo_id / "index.html").read_text()
    assert "NPS / Photographer" in photo_page
    assert 'href="https://example.com/photo" rel="noopener noreferrer"' in photo_page
    assert "Story-specific words." not in photo_page


def test_check_rejects_invalid_pair_and_unknown_photo(tmp_path: Path):
    init_project(tmp_path)
    story_file = tmp_path / "bad.story"
    story_file.write_text(
        "---\ntitle: Bad\n---\n\n@photo unknown\nlayout: pair\n",
        encoding="utf-8",
    )
    messages = [issue.message for issue in check_story(tmp_path, story_file)]
    assert "Pair layout requires exactly two photos" in messages
    assert "Unknown photo ID: unknown" in messages


def test_clean_removes_missing_entries(tmp_path: Path):
    root = tmp_path
    init_project(root)
    present = tmp_path / "originals" / "here.jpg"
    present.parent.mkdir()
    Image.new("RGB", (100, 100)).save(present)
    add_photos(root, present.parent)
    all_photos = search_photos(root, "")
    assert len(all_photos) == 1
    present.unlink()  # simulate file going missing
    removed, cache_cleared = clean_photos(root)
    assert removed == 1
    assert search_photos(root, "") == []


def test_apple_album_resolves_original_paths(tmp_path: Path, monkeypatch):
    original = tmp_path / "Photos Library.photoslibrary" / "originals" / "bison.jpg"
    edited = tmp_path / "Photos Library.photoslibrary" / "derivatives" / "bison_edit.jpg"
    original.parent.mkdir(parents=True)
    edited.parent.mkdir(parents=True)
    original.write_bytes(b"photo")
    edited.write_bytes(b"edited photo")

    class Result:
        stdout = (
            "Using last opened Photos library: /fake/Photos Library.photoslibrary\n"
            "Processing database ...\n"
            f"uuid,path,path_edited\n"
            f"aaa,{original},{edited}\n"         # edited version available
            f"bbb,{original},\n"                 # no edits, use original
            "ccc,/missing/icloud-only.heic,\n"  # iCloud only, unavailable
        )

    monkeypatch.setattr("story.photos.shutil.which", lambda name: "/bin/osxphotos")
    monkeypatch.setattr("story.photos.subprocess.run", lambda *args, **kwargs: Result())
    paths, unavailable = photos_in_apple_album("Yellowstone")
    assert paths == [edited.resolve(), original.resolve()]
    assert unavailable == 1


def test_site_build_creates_index_and_story_directories(tmp_path: Path):
    root = tmp_path
    init_project(root)
    (root / "first.story").write_text(
        "---\ntitle: First Journey\nsubtitle: Into the hills\ndate: May 2026\n---\n\nHello.\n",
        encoding="utf-8",
    )
    (root / "second.story").write_text(
        "---\ntitle: Second Journey\n---\n\nGoodbye.\n", encoding="utf-8"
    )
    (root / "site.toml").write_text(
        'title = "Family Travels"\n'
        'description = "Stories from the road."\n'
        'stories = ["first.story", "second.story"]\n',
        encoding="utf-8",
    )

    output, count, _reused = build_site(root)
    assert count == 2
    index = (output / "index.html").read_text()
    assert "Family Travels" in index
    assert "Stories from the road." in index
    assert '<a href="first/">' in index
    assert "Into the hills" in index
    assert (output / "first" / "index.html").exists()
    assert (output / "second" / "index.html").exists()
    assert 'href="../">← All stories</a>' in (output / "first" / "index.html").read_text()


def test_site_config_rejects_duplicate_story_urls(tmp_path: Path):
    init_project(tmp_path)
    (tmp_path / "one").mkdir()
    (tmp_path / "one" / "trip.story").write_text("One")
    (tmp_path / "site.toml").write_text(
        'title = "Trips"\nstories = ["one/trip.story", "one/trip.story"]\n'
    )
    try:
        load_site_config(tmp_path)
    except RuntimeError as error:
        assert "same URL" in str(error)
    else:
        raise AssertionError("duplicate story slugs should fail")


def test_site_uses_catalog_nearest_each_story_and_top_level_output(tmp_path: Path):
    source = tmp_path / "trip"
    source.mkdir()
    init_project(source)
    (source / "chapter.story").write_text("---\ntitle: Chapter\n---\n\nWords.\n")
    config = tmp_path / "site.toml"
    config.write_text('title = "Travels"\nstories = ["trip/chapter.story"]\n')

    assert find_site_config(source) == config
    output, count, _reused = build_site(tmp_path, config)
    assert count == 1
    assert output == tmp_path / "docs"
    assert (tmp_path / "docs" / "trip" / "chapter" / "index.html").exists()
    page = (tmp_path / "docs" / "trip" / "chapter" / "index.html").read_text()
    assert 'href="../../">← All stories</a>' in page
    index = (tmp_path / "docs" / "index.html").read_text()
    assert 'href="trip/chapter/"' in index
    assert '<section class="collection"><h2>Trip</h2>' in index
    assert not (source / "public").exists()


def test_site_builds_trips_from_independent_photo_catalogs(tmp_path: Path):
    story_lines = []
    for trip, color in (("yellowstone", "#8c7654"), ("san-diego", "#4f83a3")):
        source = tmp_path / trip
        originals = tmp_path / f"{trip}-originals"
        source.mkdir()
        originals.mkdir()
        photo = originals / f"{trip}.jpg"
        Image.new("RGB", (300, 200), color).save(photo)
        init_project(source)
        add_photos(source, originals)
        photo_id = search_photos(source, trip)[0]["id"]
        story_path = source / "journal.story"
        story_path.write_text(
            f"---\ntitle: {trip.title()}\n---\n\n@photo {photo_id}\n",
            encoding="utf-8",
        )
        story_lines.append(f'  "{trip}/journal.story",')

    (tmp_path / "site.toml").write_text(
        'title = "Travels"\nstories = [\n' + "\n".join(story_lines) + "\n]\n",
        encoding="utf-8",
    )
    output, count, _reused = build_site(tmp_path)
    assert count == 2
    assert (output / "yellowstone" / "journal" / "images").is_dir()
    assert (output / "san-diego" / "journal" / "images").is_dir()


def test_comments_are_stripped(tmp_path: Path):
    story_file = tmp_path / "trip.story"
    story_file.write_text(
        "---\ntitle: Yellowstone\n---\n\n"
        "// TODO: add more prose here\n"
        "We drove south.\n"
        "// another comment\n"
    )
    story = parse_story(story_file)
    prose = " ".join(n.text for n in story.nodes if n.kind == "markdown")
    assert "drove south" in prose
    assert "TODO" not in prose
    assert "comment" not in prose


def test_map_waypoints_parses(tmp_path: Path):
    story_file = tmp_path / "trip.story"
    story_file.write_text(
        "---\ntitle: Yellowstone\n---\n\nWe drove south.\n\n"
        "@map\n"
        "waypoints: 45.6770,-111.0429 44.4605,-110.8281\n"
        "caption: Bozeman to Old Faithful.\n"
        "layout: large\n"
        "\nMore prose.\n"
    )
    story = parse_story(story_file)
    map_nodes = [n for n in story.nodes if n.kind == "map"]
    assert len(map_nodes) == 1
    node = map_nodes[0]
    assert node.options["waypoints"] == "45.6770,-111.0429 44.4605,-110.8281"
    assert node.options["caption"] == "Bozeman to Old Faithful."
    assert node.options["layout"] == "large"
    assert node.photo_ids == []
    prose = [n for n in story.nodes if n.kind == "markdown"]
    assert any("drove south" in n.text for n in prose)
    assert any("More prose" in n.text for n in prose)


def test_map_gpx_parses(tmp_path: Path):
    gpx_file = tmp_path / "route.gpx"
    gpx_file.write_text(
        '<?xml version="1.0"?>\n'
        '<gpx xmlns="http://www.topografix.com/GPX/1/1">\n'
        '  <trk><trkseg>\n'
        '    <trkpt lat="45.677" lon="-111.042"></trkpt>\n'
        '    <trkpt lat="44.460" lon="-110.828"></trkpt>\n'
        '  </trkseg></trk>\n'
        '</gpx>\n'
    )
    story_file = tmp_path / "trip.story"
    story_file.write_text(
        "---\ntitle: Yellowstone\n---\n\n"
        "@map\n"
        "gpx: route.gpx\n"
        "caption: The drive in.\n"
    )
    story = parse_story(story_file)
    map_nodes = [n for n in story.nodes if n.kind == "map"]
    assert len(map_nodes) == 1
    assert map_nodes[0].options["gpx"] == "route.gpx"
    assert map_nodes[0].options["caption"] == "The drive in."


def test_map_rendered_as_figure(tmp_path: Path):
    """A map node with a known URL should render as a figure in the HTML."""
    from story.render import render_story
    from story.parser import Story, Node

    story = Story(
        metadata={"title": "Trip"},
        nodes=[Node("map", options={"caption": "Bozeman to lodge", "layout": "standard"})],
    )
    page = render_story(story, {}, lambda p: "", map_urls={0: "images/map-3.png"})
    assert 'src="images/map-3.png"' in page
    assert "Bozeman to lodge" in page
    assert '<figure class="photos standard">' in page


def test_map_places_parses(tmp_path: Path):
    story_file = tmp_path / "trip.story"
    story_file.write_text(
        "---\ntitle: Yellowstone\n---\n\n"
        "@map\n"
        "places: Bozeman MT, Old Faithful Yellowstone\n"
        "caption: The drive south.\n"
    )
    story = parse_story(story_file)
    map_nodes = [n for n in story.nodes if n.kind == "map"]
    assert len(map_nodes) == 1
    assert map_nodes[0].options["places"] == "Bozeman MT, Old Faithful Yellowstone"


def test_map_missing_url_renders_placeholder(tmp_path: Path):
    from story.render import render_story
    from story.parser import Story, Node

    story = Story(
        metadata={"title": "Trip"},
        nodes=[Node("map", options={})],
    )
    page = render_story(story, {}, lambda p: "")
    assert "Map not yet rendered" in page


def test_single_build_preserves_story_path_within_site(tmp_path: Path, monkeypatch):
    source = tmp_path / "san-diego"
    source.mkdir()
    init_project(source)
    story_file = source / "trip1.story"
    story_file.write_text("---\ntitle: San Diego\n---\n\nAt the coast.\n")
    (tmp_path / "site.toml").write_text(
        'title = "Travels"\nstories = ["san-diego/trip1.story"]\n'
    )
    monkeypatch.chdir(source)

    assert run_cli(cli_parser().parse_args(["build", "trip1.story"])) == 0
    page = tmp_path / "docs" / "san-diego" / "trip1" / "index.html"
    assert page.exists()
    assert not (source / "docs").exists()
    assert 'href="../../">← All stories</a>' in page.read_text()


def _site_with_photos(tmp_path: Path, count: int = 1):
    """A one-story site whose photos are then made unavailable, as on a second computer."""
    source = tmp_path / "yellowstone"
    originals = tmp_path / "originals"
    source.mkdir()
    originals.mkdir()
    for index in range(count):
        Image.new("RGB", (300, 200), (index * 40, 90, 60)).save(originals / f"photo{index}.jpg")
    init_project(source)
    add_photos(source, originals)
    ids = [row["id"] for row in search_photos(source, "")]
    story = source / "trip.story"
    story.write_text(
        "---\ntitle: Trip\n---\n\nWords.\n\n" + "".join(f"@photo {i}\n\n" for i in ids),
        encoding="utf-8",
    )
    (tmp_path / "site.toml").write_text('title = "Travels"\nstories = ["yellowstone/trip.story"]\n')
    return source, originals, story, ids


def _lose_photos(source: Path, originals: Path) -> None:
    import shutil
    shutil.rmtree(originals)
    shutil.rmtree(source / ".story" / "cache")


def test_site_build_reuses_unchanged_story_without_its_photos(tmp_path: Path):
    source, originals, _story, ids = _site_with_photos(tmp_path)
    output, built, reused = build_site(tmp_path)
    assert (built, reused) == (1, 0)
    assert (output / ".story-build.json").exists()

    _lose_photos(source, originals)
    output, built, reused = build_site(tmp_path)
    assert (built, reused) == (0, 1)
    assert (output / "yellowstone" / "trip" / "images" / f"{ids[0]}.webp").exists()
    assert 'href="yellowstone/trip/"' in (output / "index.html").read_text()


def test_changed_story_falls_back_to_published_images(tmp_path: Path):
    source, originals, story, ids = _site_with_photos(tmp_path)
    build_site(tmp_path)
    _lose_photos(source, originals)

    story.write_text(story.read_text() + "A fixed typo.\n", encoding="utf-8")
    output, built, reused = build_site(tmp_path)
    assert (built, reused) == (1, 0)
    page = output / "yellowstone" / "trip"
    assert "A fixed typo." in (page / "index.html").read_text()
    assert (page / "images" / f"{ids[0]}.webp").exists()


def test_missing_preview_is_regenerated_from_original(tmp_path: Path):
    source, _originals, _story, ids = _site_with_photos(tmp_path)
    preview = source / ".story" / "cache" / "previews" / f"{ids[0]}.webp"
    preview.unlink()
    output, built, _reused = build_site(tmp_path)
    assert built == 1
    assert preview.exists()
    assert (output / "yellowstone" / "trip" / "images" / f"{ids[0]}.webp").exists()


def test_unavailable_photos_are_reported_together(tmp_path: Path):
    source, originals, _story, ids = _site_with_photos(tmp_path, count=2)
    _lose_photos(source, originals)
    try:
        build_site(tmp_path)
    except RuntimeError as error:
        message = str(error)
    else:
        raise AssertionError("build should fail without any image source")
    assert "2 photo(s)" in message
    assert all(photo_id in message for photo_id in ids)
    assert "no readable original on this machine" in message
    assert not (tmp_path / "docs").exists()


def test_single_build_falls_back_to_published_images(tmp_path: Path, monkeypatch):
    source, originals, story, _ids = _site_with_photos(tmp_path)
    build_site(tmp_path)
    page = tmp_path / "docs" / "yellowstone" / "trip" / "index.html"
    before = page.read_text()
    _lose_photos(source, originals)
    story.write_text(story.read_text() + "@photo 0000000000\n", encoding="utf-8")
    monkeypatch.chdir(source)
    # The unknown ID renders as a placeholder; existing images come from the published copy.
    assert run_cli(cli_parser().parse_args(["build", "trip.story"])) == 0
    assert page.read_text() != before
    assert "Unknown photo: 0000000000" in page.read_text()


def test_single_story_build_updates_build_record(tmp_path: Path, monkeypatch):
    source, _originals, story, _ids = _site_with_photos(tmp_path)
    build_site(tmp_path)
    story.write_text(story.read_text() + "More words.\n", encoding="utf-8")
    monkeypatch.chdir(source)
    assert run_cli(cli_parser().parse_args(["build", "trip.story"])) == 0
    _output, built, reused = build_site(tmp_path)
    assert (built, reused) == (0, 1)


def test_failed_single_build_keeps_previous_output(tmp_path: Path, monkeypatch):
    source, originals, _story, ids = _site_with_photos(tmp_path, count=2)
    build_site(tmp_path)
    story_output = tmp_path / "docs" / "yellowstone" / "trip"
    (story_output / "images" / f"{ids[1]}.webp").unlink()
    _lose_photos(source, originals)
    monkeypatch.chdir(source)
    try:
        run_cli(cli_parser().parse_args(["build", "trip.story"]))
    except RuntimeError as error:
        assert ids[1] in str(error)
    else:
        raise AssertionError("build should fail when a photo has no image source")
    assert (story_output / "index.html").exists()
    assert (story_output / "images" / f"{ids[0]}.webp").exists()
    assert not list(story_output.parent.glob(".trip-*"))
