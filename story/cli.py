from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .photos import (
    add_apple_album,
    add_photos,
    clean_photos,
    rebuild_cache,
    search_photos,
    update_photo_metadata,
)
from .project import find_root, init_project
from .render import build_story
from .server import serve_photos, serve_preview
from .site import build_site, build_site_story, find_site_config
from .validate import check_story


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="story", description="Write travel stories with photographs.")
    commands = result.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="initialize a story project")
    init.add_argument("directory", nargs="?", default=".")

    photos = commands.add_parser("photos", help="browse, add, or search photographs")
    photos.add_argument(
        "action", nargs="?", choices=["add", "add-album", "search", "rebuild-cache", "set", "clean"]
    )
    photos.add_argument("values", nargs="*")
    photos.add_argument("--library", type=Path, help="an alternate Photos Library.photoslibrary")
    photos.add_argument("--host", default="127.0.0.1")
    photos.add_argument("--port", type=int, default=4173)
    photos.add_argument("--no-open", action="store_true")
    photos.add_argument("--credit", help="photographer or rights credit")
    photos.add_argument("--source-url", help="public source page for the photo")

    preview = commands.add_parser("preview", help="live-preview a .story file")
    preview.add_argument("file", type=Path)
    preview.add_argument("--host", default="127.0.0.1")
    preview.add_argument("--port", type=int, default=4173)
    preview.add_argument("--no-open", action="store_true")

    build = commands.add_parser("build", help="build a static story")
    build.add_argument("file", type=Path)
    build.add_argument("--output", type=Path)

    site = commands.add_parser("site", help="build the complete static site")
    site.add_argument("action", nargs="?", choices=["build"], default="build")
    site.add_argument("--config", type=Path, help="site configuration (default: site.toml)")

    check = commands.add_parser("check", help="validate a .story file before publishing")
    check.add_argument("file", type=Path)
    return result


def run(args: argparse.Namespace) -> int:
    if args.command == "init":
        root = Path(args.directory)
        root.mkdir(parents=True, exist_ok=True)
        created = init_project(root)
        print(("Initialized" if created else "Already initialized") + f" story project in {root.resolve()}")
        return 0
    if args.command == "photos":
        root = find_root()
        if args.action == "add":
            if len(args.values) != 1:
                raise RuntimeError("Usage: story photos add DIR")
            added, updated, skipped = add_photos(root, Path(args.values[0]))
            print(f"Added {added}; relocated {updated}; unchanged {skipped}.")
        elif args.action == "add-album":
            if len(args.values) != 1:
                raise RuntimeError('Usage: story photos add-album "ALBUM NAME"')
            added, updated, skipped, unavailable = add_apple_album(
                root, args.values[0], args.library
            )
            print(
                f"Added {added}; relocated {updated}; unchanged {skipped}; "
                f"unavailable in iCloud {unavailable}."
            )
        elif args.action == "search":
            if not args.values:
                raise RuntimeError("Usage: story photos search QUERY")
            rows = search_photos(root, " ".join(args.values))
            for row in rows:
                print(f"{row['id']}  {row['captured_at'] or 'unknown date':19}  {row['path']}")
            print(f"{len(rows)} photo(s).")
        elif args.action == "rebuild-cache":
            rebuilt, unavailable, unknown = rebuild_cache(root, args.values or None)
            print(
                f"Rebuilt {rebuilt}; unavailable originals {unavailable}; "
                f"unknown or ambiguous IDs {unknown}."
            )
            if unavailable or unknown:
                return 1
        elif args.action == "clean":
            removed, cache_cleared = clean_photos(root)
            print(f"Removed {removed} catalog entries; cleared {cache_cleared} cache files.")
        elif args.action == "set":
            if len(args.values) != 1:
                raise RuntimeError("Usage: story photos set ID [--credit TEXT] [--source-url URL]")
            photo_id = update_photo_metadata(
                root,
                args.values[0],
                credit=args.credit,
                source_url=args.source_url,
            )
            print(f"Updated photo {photo_id}.")
        else:
            serve_photos(root, args.host, args.port, not args.no_open)
        return 0
    if args.command == "preview":
        root = find_root(args.file)
        serve_preview(root, args.file, args.host, args.port, not args.no_open)
        return 0
    if args.command == "build":
        root = find_root(args.file)
        story_path = args.file.resolve()
        if args.output:
            output = build_story(root, story_path, args.output.resolve())
        else:
            try:
                config = find_site_config(story_path)
            except RuntimeError:
                output = build_story(root, story_path)
            else:
                output = build_site_story(config, story_path)
        print(f"Built {output / 'index.html'}")
        return 0
    if args.command == "site":
        config = args.config.resolve() if args.config else find_site_config()
        output, count = build_site(config.parent, config)
        print(f"Built {count} stories and {output / 'index.html'}")
        return 0
    if args.command == "check":
        root = find_root(args.file)
        issues = check_story(root, args.file.resolve())
        for issue in issues:
            print(f"{issue.severity}: {issue.message}")
        errors = sum(issue.severity == "error" for issue in issues)
        warnings = sum(issue.severity == "warning" for issue in issues)
        if not issues:
            print("Story is ready to build.")
        else:
            print(f"{errors} error(s), {warnings} warning(s).")
        return 1 if errors else 0
    return 1


def main() -> None:
    try:
        raise SystemExit(run(parser().parse_args()))
    except (RuntimeError, ValueError) as error:
        print(f"story: {error}", file=sys.stderr)
        raise SystemExit(2)
