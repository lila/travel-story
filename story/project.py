from __future__ import annotations

import sqlite3
from pathlib import Path

STATE_DIR = ".story"


def _migrate(db: sqlite3.Connection) -> None:
    table = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='photos'"
    ).fetchone()
    if not table:
        return
    columns = {row[1] for row in db.execute("PRAGMA table_info(photos)")}
    for name in ("credit", "source_url"):
        if name not in columns:
            db.execute(f"ALTER TABLE photos ADD COLUMN {name} TEXT")


def find_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / STATE_DIR / "catalog.sqlite3").exists():
            return candidate
    raise RuntimeError("Not in a story project. Run `story init` first.")


def state_dir(root: Path) -> Path:
    return root / STATE_DIR


def connect(root: Path) -> sqlite3.Connection:
    db = sqlite3.connect(state_dir(root) / "catalog.sqlite3")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    _migrate(db)
    return db


def init_project(root: Path) -> bool:
    root = root.resolve()
    state = state_dir(root)
    existed = (state / "catalog.sqlite3").exists()
    (state / "cache" / "thumbnails").mkdir(parents=True, exist_ok=True)
    (state / "cache" / "previews").mkdir(parents=True, exist_ok=True)
    with connect(root) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS photos (
                id TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL UNIQUE,
                path TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                captured_at TEXT,
                latitude REAL,
                longitude REAL,
                camera TEXT,
                lens TEXT,
                focal_length TEXT,
                aperture TEXT,
                shutter TEXT,
                iso TEXT,
                width INTEGER,
                height INTEGER,
                orientation INTEGER,
                keywords TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                imported_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS photos_captured_at ON photos(captured_at);
            CREATE INDEX IF NOT EXISTS photos_path ON photos(path);
            """
        )
        try:
            db.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS photo_search USING fts5("
                "photo_id UNINDEXED, filename, path, keywords, description)"
            )
        except sqlite3.OperationalError:
            pass
        _migrate(db)
    return not existed
