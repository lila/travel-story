from __future__ import annotations

import html
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from .parser import Story, parse_story
from .project import find_root
from .render import STYLE, build_story


SITE_STYLE = STYLE + """\
.site-header { margin-bottom:4rem }
.site-header h1 { max-width:900px }
.site-intro { max-width:640px; color:var(--muted); font-size:1.08rem }
.collection { margin-top:3.5rem }
.collection>h2 { margin:0 0 1rem; color:var(--muted); font-size:1rem; letter-spacing:.08em; text-transform:uppercase }
.story-list { list-style:none; max-width:760px; margin:0; padding:0 }
.story-list li { border-bottom:1px solid var(--rule) }
.story-list a { display:block; padding:1.6rem 0 1.8rem; text-decoration:none }
.story-list h3 { margin:0 0 .25rem; font-size:1.7rem; font-weight:400 }
.story-list p { margin:.15rem 0; color:var(--muted) }
.story-list a:hover h3 { text-decoration:underline; text-decoration-thickness:1px; text-underline-offset:.18em }
"""


@dataclass(frozen=True)
class SiteConfig:
    title: str
    description: str
    output: Path
    stories: tuple[Path, ...]


def _story_url(root: Path, story_path: Path) -> Path:
    return story_path.relative_to(root.resolve()).with_suffix("")


def _inside(root: Path, path: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise RuntimeError(f"{label} must be inside the story project: {path}") from error
    return resolved


def load_site_config(root: Path, config_path: Path | None = None) -> SiteConfig:
    path = (config_path or root / "site.toml").resolve()
    if not path.exists():
        raise RuntimeError(f"Site configuration not found: {path}")
    with path.open("rb") as config_file:
        data: dict[str, Any] = tomllib.load(config_file)

    title = str(data.get("title", "")).strip()
    if not title:
        raise RuntimeError("site.toml requires a non-empty title")
    description = str(data.get("description", "")).strip()
    output_value = data.get("output", "docs")
    if not isinstance(output_value, str) or not output_value.strip():
        raise RuntimeError("site.toml output must be a directory name")
    output = _inside(root, root / output_value, "Site output")

    story_values = data.get("stories")
    if not isinstance(story_values, list) or not story_values:
        raise RuntimeError("site.toml requires a non-empty stories list")
    stories: list[Path] = []
    urls: set[Path] = set()
    for value in story_values:
        if not isinstance(value, str):
            raise RuntimeError("Each entry in site.toml stories must be a file path")
        story_path = _inside(root, root / value, "Story file")
        if story_path.suffix != ".story" or not story_path.is_file():
            raise RuntimeError(f"Story does not exist or is not a .story file: {value}")
        url = _story_url(root, story_path)
        if url in urls:
            raise RuntimeError(f"Two stories would use the same URL: {url.as_posix()}/")
        urls.add(url)
        stories.append(story_path)
    return SiteConfig(title, description, output, tuple(stories))


def find_site_config(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        candidate = directory / "site.toml"
        if candidate.is_file():
            return candidate
    raise RuntimeError("No site.toml found in this directory or its parents")


def _render_index(root: Path, config: SiteConfig, parsed: list[tuple[Path, Story]]) -> str:
    groups: dict[Path, list[str]] = {}
    for path, story in parsed:
        relative_url = _story_url(root, path)
        url = relative_url.as_posix()
        title = story.metadata.get("title", path.stem.replace("-", " ").title())
        subtitle = story.metadata.get("subtitle")
        date = story.metadata.get("date")
        groups.setdefault(relative_url.parent, []).append(
            f'<li><a href="{html.escape(url)}/"><h3>{html.escape(title)}</h3>'
            + (f'<p>{html.escape(subtitle)}</p>' if subtitle else "")
            + (f'<p>{html.escape(date)}</p>' if date else "")
            + "</a></li>"
        )
    collections: list[str] = []
    for directory, entries in groups.items():
        if directory == Path("."):
            label = "Stories"
        else:
            label = " / ".join(part.replace("-", " ").title() for part in directory.parts)
        collections.append(
            f'<section class="collection"><h2>{html.escape(label)}</h2>'
            f'<ol class="story-list">{"".join(entries)}</ol></section>'
        )
    description = (
        f'<p class="site-intro">{html.escape(config.description)}</p>'
        if config.description
        else ""
    )
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(config.title)}</title><link rel="stylesheet" href="style.css"></head><body><main><header class="site-header"><h1>{html.escape(config.title)}</h1>{description}</header>{''.join(collections)}</main></body></html>"""


def build_site(root: Path, config_path: Path | None = None) -> tuple[Path, int]:
    config = load_site_config(root, config_path)
    parsed = [(path, parse_story(path)) for path in config.stories]
    stage = Path(tempfile.mkdtemp(prefix=".site-build-", dir=root))

    try:
        for story_path, _story in parsed:
            catalog_root = find_root(story_path)
            relative_url = _story_url(root, story_path)
            output_base = stage / relative_url.parent
            home_url = "../" * len(relative_url.parts)
            build_story(catalog_root, story_path, output_base, home_url=home_url)
        (stage / "index.html").write_text(
            _render_index(root, config, parsed), encoding="utf-8"
        )
        (stage / "style.css").write_text(SITE_STYLE, encoding="utf-8")

        if config.output.exists():
            if not config.output.is_dir() or config.output.is_symlink():
                raise RuntimeError(f"Site output destination is unsafe: {config.output}")
            shutil.rmtree(config.output)
        config.output.parent.mkdir(parents=True, exist_ok=True)
        stage.replace(config.output)
    except Exception:
        if stage.exists() and stage.is_dir() and not stage.is_symlink():
            shutil.rmtree(stage)
        raise
    return config.output, len(parsed)


def build_site_story(config_path: Path, story_path: Path) -> Path:
    """Build one story into its path within an existing publication."""
    site_root = config_path.resolve().parent
    config = load_site_config(site_root, config_path)
    story_path = _inside(site_root, story_path, "Story file")
    relative_url = _story_url(site_root, story_path)
    output_base = config.output / relative_url.parent
    home_url = "../" * len(relative_url.parts)
    return build_story(
        find_root(story_path),
        story_path,
        output_base,
        home_url=home_url,
    )
