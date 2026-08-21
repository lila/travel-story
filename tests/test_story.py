from pathlib import Path

from PIL import Image

from story.parser import parse_story
from story.cli import parser as cli_parser, run as run_cli
from story.photos import (
    add_photos,
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


def test_apple_album_resolves_original_paths(tmp_path: Path, monkeypatch):
    original = tmp_path / "Photos Library.photoslibrary" / "originals" / "bison.jpg"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"photo")

    class Result:
        stdout = f"{original}\n/missing/icloud-only.heic\n"

    monkeypatch.setattr("story.photos.shutil.which", lambda name: "/bin/osxphotos")
    monkeypatch.setattr("story.photos.subprocess.run", lambda *args, **kwargs: Result())
    paths, unavailable = photos_in_apple_album("Yellowstone")
    assert paths == [original]
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

    output, count = build_site(root)
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
    output, count = build_site(tmp_path, config)
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
    output, count = build_site(tmp_path)
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
