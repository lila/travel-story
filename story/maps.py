from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from .parser import Node
from .project import state_dir

_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_USER_AGENT = "travel-story/0.1 (+https://github.com/lila/travel-story)"
_MAP_WIDTH = 1200
_MAP_HEIGHT = 800


def _parse_gpx(path: Path) -> list[tuple[float, float]]:
    """Return (lon, lat) pairs from a GPX track or waypoint file."""
    ns = {"gpx": "http://www.topografix.com/GPX/1/1"}
    root = ET.parse(path).getroot()
    coords: list[tuple[float, float]] = []
    for trkpt in root.findall(".//gpx:trkpt", ns):
        coords.append((float(trkpt.get("lon")), float(trkpt.get("lat"))))
    if not coords:
        for wpt in root.findall(".//gpx:wpt", ns):
            coords.append((float(wpt.get("lon")), float(wpt.get("lat"))))
    return coords


def _parse_waypoints(value: str) -> list[tuple[float, float]]:
    """Parse 'lat,lon lat,lon ...' string into (lon, lat) pairs for staticmap."""
    coords: list[tuple[float, float]] = []
    for pair in value.split():
        lat_s, lon_s = pair.split(",", 1)
        coords.append((float(lon_s), float(lat_s)))
    return coords


def _geocode_one(name: str, geocode_cache: Path) -> tuple[float, float]:
    """Return (lon, lat) for a place name, caching the result on disk."""
    key = hashlib.sha256(name.lower().strip().encode()).hexdigest()[:20]
    cached = geocode_cache / f"{key}.json"
    if cached.exists():
        data = json.loads(cached.read_text(encoding="utf-8"))
        return data["lon"], data["lat"]

    url = _NOMINATIM_URL + "?" + urllib.parse.urlencode({"q": name, "format": "json", "limit": 1})
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=10) as resp:
        results = json.loads(resp.read())

    if not results:
        raise RuntimeError(f"Could not geocode place: {name!r}")

    lon = float(results[0]["lon"])
    lat = float(results[0]["lat"])
    cached.write_text(
        json.dumps({"lon": lon, "lat": lat, "display": results[0]["display_name"]}),
        encoding="utf-8",
    )
    time.sleep(1)  # Nominatim requires max 1 request per second
    return lon, lat


def _parse_places(value: str, geocode_cache: Path) -> list[tuple[float, float]]:
    """Geocode a comma-separated list of place names into (lon, lat) pairs."""
    names = [p.strip() for p in value.split(",") if p.strip()]
    return [_geocode_one(name, geocode_cache) for name in names]


def _cache_key(node: Node, story_path: Path) -> str:
    h = hashlib.sha256()
    gpx = node.options.get("gpx")
    if gpx:
        gpx_path = story_path.parent / gpx
        if gpx_path.is_file():
            h.update(gpx_path.read_bytes())
        else:
            h.update(gpx.encode())
    h.update(node.options.get("waypoints", "").encode())
    h.update(node.options.get("places", "").encode())
    return h.hexdigest()[:20]


def get_coords(node: Node, story_path: Path, root: Path | None = None) -> list[tuple[float, float]]:
    """Resolve coordinates from a map node's gpx:, waypoints:, or places: option."""
    gpx = node.options.get("gpx")
    waypoints = node.options.get("waypoints")
    places = node.options.get("places")
    if gpx:
        gpx_path = story_path.parent / gpx
        if not gpx_path.is_file():
            raise RuntimeError(f"GPX file not found: {gpx}")
        coords = _parse_gpx(gpx_path)
    elif waypoints:
        coords = _parse_waypoints(waypoints)
    elif places:
        if root is None:
            raise RuntimeError("places: geocoding requires a project root")
        geocode_cache = state_dir(root) / "cache" / "geocode"
        geocode_cache.mkdir(parents=True, exist_ok=True)
        coords = _parse_places(places, geocode_cache)
    else:
        raise RuntimeError("@map requires gpx:, waypoints:, or places:")
    if len(coords) < 2:
        raise RuntimeError("@map needs at least two coordinate points")
    return coords


def build_map_image(root: Path, story_path: Path, node: Node) -> Path:
    """Render a static map for a @map node; return the path to the cached PNG.

    The result is cached in .story/cache/maps/ keyed by the content of the
    GPX file or waypoint string, so repeated builds do not re-fetch tiles.
    """
    try:
        from staticmap import CircleMarker, Line, StaticMap
    except ImportError:
        raise RuntimeError(
            "@map directives require the staticmap library. "
            "Install it with: pip install staticmap"
        )

    cache_dir = state_dir(root) / "cache" / "maps"
    cache_dir.mkdir(parents=True, exist_ok=True)

    cached = cache_dir / f"{_cache_key(node, story_path)}.png"
    if cached.exists():
        return cached

    coords = get_coords(node, story_path, root)

    m = StaticMap(_MAP_WIDTH, _MAP_HEIGHT, url_template=_TILE_URL)
    m.add_line(Line(coords, "#c0392b", 3))
    m.add_marker(CircleMarker(coords[0], "#2c3e50", 14))
    m.add_marker(CircleMarker(coords[-1], "#2c3e50", 14))

    image = m.render()
    image.save(str(cached))
    return cached
