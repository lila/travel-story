from pathlib import Path

from PIL import Image

from story.parser import parse_story
from story.photos import (
    add_photos,
    photos_in_apple_album,
    rebuild_cache,
    search_photos,
    update_photo_metadata,
)
from story.project import init_project
from story.render import STYLE, build_story
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


def test_pair_layout_uses_matching_cropped_frames():
    assert ".photos.pair img" in STYLE
    assert "aspect-ratio:3/2" in STYLE
    assert "object-fit:cover" in STYLE


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
