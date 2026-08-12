from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Node:
    kind: str
    text: str = ""
    photo_ids: list[str] = field(default_factory=list)
    options: dict[str, str] = field(default_factory=dict)


@dataclass
class Story:
    metadata: dict[str, str]
    nodes: list[Node]

    @property
    def photo_ids(self) -> list[str]:
        return [photo_id for node in self.nodes for photo_id in node.photo_ids]


def _front_matter(lines: list[str]) -> tuple[dict[str, str], list[str]]:
    if not lines or lines[0].strip() != "---":
        return {}, lines
    metadata: dict[str, str] = {}
    for index, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return metadata, lines[index + 1:]
        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip().lower()] = value.strip().strip('"\'')
    raise ValueError("Unclosed front matter (expected a second --- line)")


def parse_story(path: Path) -> Story:
    metadata, lines = _front_matter(path.read_text(encoding="utf-8").splitlines())
    lines = [line for line in lines if not line.lstrip().startswith("//")]
    nodes: list[Node] = []
    prose: list[str] = []

    def flush() -> None:
        if prose and any(line.strip() for line in prose):
            nodes.append(Node("markdown", "\n".join(prose).strip()))
        prose.clear()

    index = 0
    while index < len(lines):
        photo_match = re.match(r"^@(photo|photos)\s+(.+?)\s*$", lines[index])
        map_match = re.match(r"^@map\s*$", lines[index])
        if not photo_match and not map_match:
            prose.append(lines[index])
            index += 1
            continue
        flush()
        if map_match:
            kind = "map"
            ids: list[str] = []
        else:
            ids = photo_match.group(2).split()  # type: ignore[union-attr]
            if photo_match.group(1) == "photo":  # type: ignore[union-attr]
                ids = ids[:1]
            kind = "photos"
        options: dict[str, str] = {}
        index += 1
        while index < len(lines):
            option = re.match(
                r"^(layout|caption|relationship|gpx|waypoints|places):\s*(.+)$",
                lines[index],
                re.I,
            )
            if not option:
                break
            options[option.group(1).lower()] = option.group(2).strip()
            index += 1
        nodes.append(Node(kind, photo_ids=ids, options=options))
    flush()
    return Story(metadata, nodes)

