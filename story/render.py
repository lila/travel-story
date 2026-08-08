from __future__ import annotations

import html
import re
import shutil
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

import markdown
from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor

from .parser import Story
from .photos import get_photos
from .project import state_dir

STYLE = """\
:root { color-scheme: light; --ink:#24231f; --muted:#77736a; --paper:#fbfaf7; --rule:#dedbd2; --focus:#7b4b16; }
* { box-sizing:border-box } body { margin:0; background:var(--paper); color:var(--ink); font:18px/1.68 "Iowan Old Style",Charter,"Bitstream Charter",Palatino,Georgia,serif }
main { max-width:760px; margin:7vw auto 12vw; padding:0 24px } header { border-bottom:1px solid var(--rule); padding-bottom:2.5rem; margin-bottom:3.5rem } h1 { font-size:clamp(2.6rem,7vw,5rem); line-height:1.02; font-weight:400; letter-spacing:-.035em; margin:.2em 0 }
h2 { font-weight:400; font-size:1.65rem; margin-top:3em; margin-bottom:.7em } main>p,main>h2,main>h3,main>ul,main>ol,main>blockquote { max-width:640px; margin-left:auto; margin-right:auto } .deck,.date { color:var(--muted) } p { margin-top:1.25em; margin-bottom:1.25em } a { color:inherit; text-decoration-color:#aaa69c; text-decoration-thickness:1px; text-underline-offset:.16em } a:hover { text-decoration-color:currentColor } a:focus-visible { outline:2px solid var(--focus); outline-offset:4px }
figure { margin:3.5em 0 } figure img { display:block; width:100%; height:auto; background:#eee } figcaption { grid-column:1/-1; color:var(--muted); font-size:.88rem; line-height:1.45; margin-top:.8em }
.photo-link { display:block; text-decoration:none }
.photos { display:grid; gap:12px } .photos.standard { max-width:640px; margin-left:auto; margin-right:auto } .photos.large { width:min(88vw,1050px); margin-left:50%; transform:translateX(-50%) } .photos.pair { grid-template-columns:repeat(2,minmax(0,1fr)); margin-left:-8vw; margin-right:-8vw }
.photos.pair img { width:100%; aspect-ratio:3/2; object-fit:cover }
.photos.full { width:min(96vw,1400px); margin-left:50%; transform:translateX(-50%) } .missing { border:1px solid var(--rule); padding:2em; color:#9b3c31 }
.photo-detail { max-width:1200px } .photo-detail>img { display:block; width:100%; height:auto }
.metadata { max-width:760px; display:grid; grid-template-columns:max-content 1fr; gap:.35rem 1.5rem; border-top:1px solid var(--rule); padding-top:1.5rem; margin-top:2.5rem; font-size:.92rem } .metadata dt { color:var(--muted) } .metadata dd { margin:0 } .back { display:inline-block; margin-bottom:1.5rem; font-size:.92rem }
@media(max-width:700px) { body { font-size:17px } main { margin-top:40px; padding:0 18px } header { padding-bottom:1.75rem; margin-bottom:2.5rem } .photos.pair { margin-left:0; margin-right:0; grid-template-columns:1fr } .photos.large,.photos.full { width:calc(100vw - 24px) } .metadata { grid-template-columns:1fr; gap:.1rem } .metadata dd { margin-bottom:.65rem } }
"""


class _ExternalLinks(Treeprocessor):
    def run(self, root):
        for element in root.iter("a"):
            href = element.get("href", "")
            if href.startswith(("http://", "https://", "//")):
                element.set("rel", "noopener noreferrer")
        return root


class _ExternalLinkExtension(Extension):
    def extendMarkdown(self, md):
        md.treeprocessors.register(_ExternalLinks(md), "external_links", 5)


def _render_markdown(text: str) -> str:
    return markdown.markdown(text, extensions=["smarty", _ExternalLinkExtension()])


def render_story(
    story: Story,
    photos: dict[str, Any],
    image_url: Callable[[Any], str],
    photo_page_url: Callable[[Any], str] | None = None,
    live: bool = False,
) -> str:
    title = story.metadata.get("title", "Untitled story")
    body: list[str] = []
    first_markdown = True
    for node in story.nodes:
        if node.kind == "markdown":
            text = node.text
            if first_markdown:
                # Let a story remain readable as standalone Markdown without
                # printing its title twice when front matter supplies it too.
                heading = re.match(r"^#\s+(.+?)\s*(?:\n|$)", text)
                if heading and heading.group(1).strip() == title.strip():
                    text = text[heading.end():].lstrip()
            if text:
                body.append(_render_markdown(text))
            first_markdown = False
            continue
        layout = node.options.get("layout", "pair" if len(node.photo_ids) == 2 else "standard")
        images = []
        for requested_id in node.photo_ids:
            photo = photos.get(requested_id)
            if photo is None:
                images.append(f'<div class="missing">Unknown photo: {html.escape(requested_id)}</div>')
            else:
                alt = node.options.get("caption", photo["description"] or photo["filename"])
                image = f'<img src="{html.escape(image_url(photo))}" alt="{html.escape(alt)}" loading="lazy">'
                if photo_page_url is not None:
                    label = f"View details for {alt}"
                    image = f'<a class="photo-link" href="{html.escape(photo_page_url(photo))}" aria-label="{html.escape(label)}">{image}</a>'
                images.append(image)
        caption = node.options.get("caption")
        body.append(f'<figure class="photos {html.escape(layout)}">' + "".join(images) + (f'<figcaption>{html.escape(caption)}</figcaption>' if caption else "") + "</figure>")
    subtitle = story.metadata.get("subtitle")
    date = story.metadata.get("date")
    live_script = """
<script>let v='';setInterval(async()=>{try{let n=await(await fetch('/__version',{cache:'no-store'})).text();if(v&&n!==v)location.reload();v=n}catch(e){}},700)</script>""" if live else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><link rel="stylesheet" href="style.css"></head><body><main><header><h1>{html.escape(title)}</h1>{f'<p class="deck">{html.escape(subtitle)}</p>' if subtitle else ''}{f'<p class="date">{html.escape(date)}</p>' if date else ''}</header>{''.join(body)}</main>{live_script}</body></html>"""


def _exposure(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return str(value)
    if 0 < seconds < 1:
        fraction = Fraction(seconds).limit_denominator(8000)
        return f"{fraction.numerator}/{fraction.denominator} s"
    return f"{seconds:g} s"


def _photo_metadata(photo: Any) -> list[tuple[str, str]]:
    fields: list[tuple[str, str | None]] = [
        ("Captured", photo["captured_at"]),
        ("Camera", photo["camera"]),
        ("Lens", photo["lens"]),
        ("Focal length", f'{photo["focal_length"]} mm' if photo["focal_length"] else None),
        ("Aperture", f'f/{photo["aperture"]}' if photo["aperture"] else None),
        ("Shutter", _exposure(photo["shutter"])),
        ("Sensitivity", f'ISO {photo["iso"]}' if photo["iso"] else None),
        ("Dimensions", f'{photo["width"]} × {photo["height"]}' if photo["width"] and photo["height"] else None),
        ("Credit", photo["credit"]),
        ("Photo ID", photo["id"]),
    ]
    return [(label, str(value)) for label, value in fields if value not in (None, "")]


def render_photo_page(
    photo: Any,
    image_url: str,
    back_url: str,
    stylesheet_url: str,
    story_title: str,
) -> str:
    title = f'Photo {photo["id"]}'
    metadata = "".join(
        f'<dt>{html.escape(label)}</dt><dd>{html.escape(value)}</dd>'
        for label, value in _photo_metadata(photo)
    )
    if photo["source_url"]:
        source = html.escape(photo["source_url"])
        metadata += f'<dt>Source</dt><dd><a href="{source}" rel="noopener noreferrer">Original source</a></dd>'
    alt = photo["description"] or f'Photograph {photo["id"]}'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><link rel="stylesheet" href="{html.escape(stylesheet_url)}"></head><body><main class="photo-detail"><a class="back" href="{html.escape(back_url)}">← Back to {html.escape(story_title)}</a><img src="{html.escape(image_url)}" alt="{html.escape(alt)}"><dl class="metadata">{metadata}</dl></main></body></html>"""


def build_story(root: Path, story_path: Path, output_base: Path | None = None) -> Path:
    from .parser import parse_story
    story = parse_story(story_path)
    photos = get_photos(root, story.photo_ids)
    slug = story_path.stem
    output = (output_base or root / "public") / slug
    images = output / "images"
    if output.exists():
        if not output.is_dir() or output.is_symlink():
            raise RuntimeError(f"Build destination is not a directory: {output}")
        shutil.rmtree(output)
    images.mkdir(parents=True, exist_ok=True)

    def copy_image(photo: Any) -> str:
        name = f"{photo['id']}.webp"
        cached = state_dir(root) / "cache" / "previews" / name
        if not cached.exists():
            raise RuntimeError(f"No renderable preview for photo {photo['id']} ({photo['path']})")
        shutil.copy2(cached, images / name)
        return f"images/{name}"

    page = render_story(story, photos, copy_image, lambda photo: f"photos/{photo['id']}/")
    (output / "index.html").write_text(page, encoding="utf-8")
    (output / "style.css").write_text(STYLE, encoding="utf-8")

    for photo in {row["id"]: row for row in photos.values()}.values():
        photo_output = output / "photos" / photo["id"]
        photo_output.mkdir(parents=True, exist_ok=True)
        detail = render_photo_page(
            photo,
            f"../../images/{photo['id']}.webp",
            "../../",
            "../../style.css",
            story.metadata.get("title", "story"),
        )
        (photo_output / "index.html").write_text(detail, encoding="utf-8")
    return output
