from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .maps import get_coords
from .parser import parse_story
from .project import connect, state_dir


VALID_LAYOUTS = {"standard", "large", "full", "pair"}


@dataclass(frozen=True)
class Issue:
    severity: str
    message: str


def check_story(root: Path, story_path: Path) -> list[Issue]:
    story = parse_story(story_path)
    issues: list[Issue] = []
    if not story.metadata.get("title"):
        issues.append(Issue("warning", "Story has no title in front matter"))

    for node in story.nodes:
        if node.kind != "map":
            continue
        has_source = node.options.get("gpx") or node.options.get("waypoints") or node.options.get("places")
        if not has_source:
            issues.append(Issue("error", "@map requires gpx:, waypoints:, or places:"))
            continue
        layout = node.options.get("layout", "standard").lower()
        if layout not in VALID_LAYOUTS:
            issues.append(Issue("error", f"Unknown map layout: {layout}"))
        places = node.options.get("places")
        if places:
            count = len([p for p in places.split(",") if p.strip()])
            if count < 2:
                issues.append(Issue("error", "places: requires at least two place names"))
        else:
            try:
                get_coords(node, story_path)
            except RuntimeError as exc:
                issues.append(Issue("error", str(exc)))

    with connect(root) as db:
        for node in story.nodes:
            if node.kind != "photos":
                continue
            layout = node.options.get(
                "layout", "pair" if len(node.photo_ids) == 2 else "standard"
            ).lower()
            if layout not in VALID_LAYOUTS:
                issues.append(Issue("error", f"Unknown photo layout: {layout}"))
            if layout == "pair" and len(node.photo_ids) != 2:
                issues.append(Issue("error", "Pair layout requires exactly two photos"))

            for requested_id in node.photo_ids:
                rows = list(
                    db.execute(
                        "SELECT id, path FROM photos WHERE id LIKE ? ORDER BY id LIMIT 2",
                        (requested_id + "%",),
                    )
                )
                if not rows:
                    issues.append(Issue("error", f"Unknown photo ID: {requested_id}"))
                    continue
                if len(rows) > 1:
                    issues.append(
                        Issue("error", f"Ambiguous photo ID prefix: {requested_id}")
                    )
                    continue
                photo = rows[0]
                if not Path(photo["path"]).is_file():
                    issues.append(
                        Issue("error", f'Original is missing for photo {photo["id"]}')
                    )
                preview = state_dir(root) / "cache" / "previews" / f'{photo["id"]}.webp'
                thumbnail = state_dir(root) / "cache" / "thumbnails" / f'{photo["id"]}.webp'
                if not preview.is_file():
                    issues.append(
                        Issue("error", f'Preview cache is missing for photo {photo["id"]}')
                    )
                if not thumbnail.is_file():
                    issues.append(
                        Issue("warning", f'Thumbnail cache is missing for photo {photo["id"]}')
                    )
    return issues
