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
    nodes: list[Node] = []
    prose: list[str] = []

    def flush() -> None:
        if prose and any(line.strip() for line in prose):
            nodes.append(Node("markdown", "\n".join(prose).strip()))
        prose.clear()

    index = 0
    while index < len(lines):
        match = re.match(r"^@(photo|photos)\s+(.+?)\s*$", lines[index])
        if not match:
            prose.append(lines[index])
            index += 1
            continue
        flush()
        ids = match.group(2).split()
        if match.group(1) == "photo":
            ids = ids[:1]
        options: dict[str, str] = {}
        index += 1
        while index < len(lines):
            option = re.match(r"^(layout|caption|relationship):\s*(.+)$", lines[index], re.I)
            if not option:
                break
            options[option.group(1).lower()] = option.group(2).strip()
            index += 1
        nodes.append(Node("photos", photo_ids=ids, options=options))
    flush()
    return Story(metadata, nodes)

