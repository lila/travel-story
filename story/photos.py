from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageOps
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

from .project import connect, state_dir

PHOTO_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".heic", ".heif",
    ".dng", ".raf", ".cr2", ".cr3", ".nef", ".arw", ".orf", ".rw2",
}


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _exiftool(paths: list[Path]) -> dict[str, dict[str, Any]]:
    executable = shutil.which("exiftool")
    if not executable or not paths:
        return {}
    command = [
        executable, "-json", "-n", "-DateTimeOriginal", "-GPSLatitude",
        "-GPSLongitude", "-Make", "-Model", "-LensModel", "-FocalLength",
        "-FNumber", "-ExposureTime", "-ISO", "-ImageWidth", "-ImageHeight",
        "-Orientation", *map(str, paths),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        rows = json.loads(result.stdout)
        return {str(Path(row["SourceFile"]).resolve()): row for row in rows}
    except (subprocess.SubprocessError, json.JSONDecodeError, KeyError):
        return {}


def _pillow_metadata(path: Path) -> dict[str, Any]:
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            return {
                "ImageWidth": image.width,
                "ImageHeight": image.height,
                "Orientation": exif.get(274),
                "DateTimeOriginal": exif.get(36867),
                "Make": exif.get(271),
                "Model": exif.get(272),
            }
    except (OSError, ValueError):
        return {}


def _value(row: dict[str, Any], key: str) -> Any:
    value = row.get(key)
    return str(value) if value is not None else None


def _make_derivative(source: Path, destination: Path, max_size: int) -> bool:
    try:
        with Image.open(source) as image:
            image = ImageOps.exif_transpose(image)
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            destination.parent.mkdir(parents=True, exist_ok=True)
            image.save(destination, "WEBP", quality=86, method=4)
        return True
    except (OSError, ValueError):
        return False


def add_photos(root: Path, directory: Path) -> tuple[int, int, int]:
    directory = directory.expanduser().resolve()
    if not directory.is_dir():
        raise RuntimeError(f"Photo directory does not exist: {directory}")
    paths = sorted(
        path for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in PHOTO_EXTENSIONS
    )
    return add_photo_paths(root, paths)


def photos_in_apple_album(album: str, library: Path | None = None) -> tuple[list[Path], int]:
    """Return locally available photo paths from an Apple Photos album.

    OSXPhotos reads the Photos database without exporting or modifying assets.
    The edited version of a photo is preferred over the original when available,
    so brightness, contrast, and crop adjustments made in Photos are reflected
    in the story. Photos available only in iCloud are counted as unavailable.
    """
    executable = shutil.which("osxphotos")
    if not executable:
        raise RuntimeError(
            "Apple Photos album support currently requires a working external "
            "`osxphotos` command. Nixpkgs marks it broken on macOS; native "
            "PhotoKit support is still needed."
        )
    command = [executable, "query", "--album", album, "--quiet"]
    if library is not None:
        library = library.expanduser().resolve()
        command.extend(["--library", str(library)])
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout).strip()
        raise RuntimeError(f"Could not read Apple Photos album {album!r}: {detail}") from error
    paths: list[Path] = []
    unavailable = 0
    for row in csv.DictReader(io.StringIO(result.stdout)):
        edited = (row.get("path_edited") or "").strip()
        original = (row.get("path") or "").strip()
        if edited and Path(edited).is_file():
            paths.append(Path(edited).resolve())
        elif original and Path(original).is_file():
            paths.append(Path(original).resolve())
        else:
            unavailable += 1
    return paths, unavailable


def add_apple_album(
    root: Path, album: str, library: Path | None = None
) -> tuple[int, int, int, int]:
    paths, unavailable = photos_in_apple_album(album, library)
    if not paths and not unavailable:
        raise RuntimeError(
            f"No photos found in Apple Photos album {album!r}. "
            "Check the album name and Photos library permissions."
        )
    added, updated, skipped = add_photo_paths(root, paths)
    return added, updated, skipped, unavailable


def add_photo_paths(root: Path, paths: Iterable[Path]) -> tuple[int, int, int]:
    paths = sorted(
        path.resolve() for path in paths
        if path.is_file() and path.suffix.lower() in PHOTO_EXTENSIONS
    )
    metadata = _exiftool(paths)
    added = updated = skipped = 0
    with connect(root) as db:
        for path in paths:
            digest = file_hash(path)
            existing = db.execute(
                "SELECT id, path FROM photos WHERE content_hash = ?", (digest,)
            ).fetchone()
            if existing:
                if existing["path"] != str(path):
                    db.execute("UPDATE photos SET path=?, filename=? WHERE id=?", (str(path), path.name, existing["id"]))
                    updated += 1
                else:
                    skipped += 1
                continue
            # Twelve characters are pleasant to copy. In the extremely unlikely
            # event of a prefix collision, reveal more of the same content hash.
            length = 12
            while db.execute("SELECT 1 FROM photos WHERE id = ?", (digest[:length],)).fetchone():
                length += 2
            photo_id = digest[:length]
            row = metadata.get(str(path), {}) or _pillow_metadata(path)
            camera = " ".join(filter(None, (_value(row, "Make"), _value(row, "Model")))) or None
            values = (
                photo_id, digest, str(path), path.name, path.stat().st_size,
                _value(row, "DateTimeOriginal"), row.get("GPSLatitude"), row.get("GPSLongitude"),
                camera, _value(row, "LensModel"), _value(row, "FocalLength"),
                _value(row, "FNumber"), _value(row, "ExposureTime"), _value(row, "ISO"),
                row.get("ImageWidth"), row.get("ImageHeight"), row.get("Orientation"),
                datetime.now(timezone.utc).isoformat(),
            )
            db.execute(
                """INSERT INTO photos (
                id, content_hash, path, filename, file_size, captured_at, latitude,
                longitude, camera, lens, focal_length, aperture, shutter, iso,
                width, height, orientation, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                values,
            )
            try:
                db.execute(
                    "INSERT INTO photo_search(photo_id, filename, path, keywords, description) VALUES (?, ?, ?, '', '')",
                    (photo_id, path.name, str(path)),
                )
            except Exception:
                pass
            cache = state_dir(root) / "cache"
            _make_derivative(path, cache / "thumbnails" / f"{photo_id}.webp", 480)
            _make_derivative(path, cache / "previews" / f"{photo_id}.webp", 1800)
            added += 1
    return added, updated, skipped


def search_photos(root: Path, query: str, limit: int = 50) -> list[Any]:
    with connect(root) as db:
        if not query.strip():
            return list(db.execute("SELECT * FROM photos ORDER BY captured_at DESC, filename LIMIT ?", (limit,)))
        words = [word.replace('"', '') for word in query.split() if word.replace('"', '')]
        fts_query = " AND ".join(f'"{word}"*' for word in words)
        try:
            return list(db.execute(
                """SELECT p.* FROM photo_search s JOIN photos p ON p.id=s.photo_id
                WHERE photo_search MATCH ? ORDER BY rank LIMIT ?""", (fts_query, limit)
            ))
        except sqlite3.OperationalError:
            pattern = f"%{query}%"
            return list(db.execute(
                "SELECT * FROM photos WHERE filename LIKE ? OR path LIKE ? OR keywords LIKE ? OR description LIKE ? LIMIT ?",
                (pattern, pattern, pattern, pattern, limit),
            ))


def get_photos(root: Path, ids: Iterable[str]) -> dict[str, Any]:
    result = {}
    with connect(root) as db:
        for photo_id in ids:
            rows = list(db.execute("SELECT * FROM photos WHERE id LIKE ? ORDER BY id LIMIT 2", (photo_id + "%",)))
            if len(rows) == 1:
                result[photo_id] = rows[0]
    return result


def rebuild_cache(root: Path, ids: Iterable[str] | None = None) -> tuple[int, int, int]:
    requested = list(ids or [])
    with connect(root) as db:
        if requested:
            rows = []
            unknown = 0
            for photo_id in requested:
                matches = list(
                    db.execute(
                        "SELECT * FROM photos WHERE id LIKE ? ORDER BY id LIMIT 2",
                        (photo_id + "%",),
                    )
                )
                if len(matches) == 1:
                    rows.append(matches[0])
                else:
                    unknown += 1
        else:
            rows = list(db.execute("SELECT * FROM photos ORDER BY id"))
            unknown = 0

    rebuilt = unavailable = 0
    cache = state_dir(root) / "cache"
    for row in {item["id"]: item for item in rows}.values():
        source = Path(row["path"])
        if not source.is_file():
            unavailable += 1
            continue
        thumbnail = _make_derivative(
            source, cache / "thumbnails" / f'{row["id"]}.webp', 480
        )
        preview = _make_derivative(
            source, cache / "previews" / f'{row["id"]}.webp', 1800
        )
        if thumbnail and preview:
            rebuilt += 1
        else:
            unavailable += 1
    return rebuilt, unavailable, unknown


def clean_photos(root: Path) -> tuple[int, int]:
    """Remove catalog entries whose original file no longer exists on disk.

    Also removes the corresponding thumbnail and preview cache files.
    Returns (entries_removed, cache_files_cleared).
    """
    removed_ids: list[str] = []
    with connect(root) as db:
        for row in db.execute("SELECT id, path FROM photos"):
            if not Path(row["path"]).is_file():
                db.execute("DELETE FROM photos WHERE id = ?", (row["id"],))
                db.execute("DELETE FROM photo_search WHERE photo_id = ?", (row["id"],))
                removed_ids.append(row["id"])

    cache = state_dir(root) / "cache"
    cache_cleared = 0
    for photo_id in removed_ids:
        for folder in ("thumbnails", "previews"):
            f = cache / folder / f"{photo_id}.webp"
            if f.exists():
                f.unlink()
                cache_cleared += 1
    return len(removed_ids), cache_cleared


def update_photo_metadata(
    root: Path,
    photo_id: str,
    *,
    credit: str | None = None,
    source_url: str | None = None,
) -> str:
    with connect(root) as db:
        rows = list(
            db.execute(
                "SELECT id FROM photos WHERE id LIKE ? ORDER BY id LIMIT 2",
                (photo_id + "%",),
            )
        )
        if not rows:
            raise RuntimeError(f"Unknown photo ID: {photo_id}")
        if len(rows) > 1:
            raise RuntimeError(f"Ambiguous photo ID prefix: {photo_id}")
        canonical = rows[0]["id"]
        if credit is None and source_url is None:
            raise RuntimeError("Provide --credit and/or --source-url")
        assignments = []
        values: list[str | None] = []
        if credit is not None:
            assignments.append("credit = ?")
            values.append(credit.strip() or None)
        if source_url is not None:
            source_url = source_url.strip()
            if source_url and not source_url.startswith(("http://", "https://")):
                raise RuntimeError("--source-url must begin with http:// or https://")
            assignments.append("source_url = ?")
            values.append(source_url or None)
        db.execute(
            f"UPDATE photos SET {', '.join(assignments)} WHERE id = ?",
            (*values, canonical),
        )
    return canonical
