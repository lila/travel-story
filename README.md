# Travel Story

Travel Story is a small writer's tool for making quiet, photographic travel
essays. You write a plain-text `.story` file in any editor. The tool catalogs
photos where they already live, gives them stable IDs, previews the story in a
browser, and builds ordinary static HTML, CSS, and images.

It is deliberately not a CMS, photo organizer, or editor.

## Motivation and principles

Travel Story takes inspiration from [Philip Greenspun's travel
writing](https://philip.greenspun.com/travel/), especially [*Travels with
Samantha*](https://philip.greenspun.com/samantha/), and from the early
photo.net tradition of using straightforward software to publish
carefully authored material. The aim is not to reproduce the old site or its
Oracle-and-Tcl stack. It is to preserve something valuable in its approach:
prose and photographs belong to the same narrative, and the machinery should
remain behind the work.

These principles guide the project:

- **The story is the unit of composition.** It is a linear illustrated
  narrative, not a feed, gallery, collection of cards, or pile of CMS blocks.
- **Writing comes first.** Photographs can interrupt, answer, or extend the
  prose. They are not decoration around it.
- **Captions are part of the story.** A caption may carry observation,
  context, humor, or photographic judgment rather than merely identify a file.
- **Narrative relevance beats prettiness.** The right photograph may be quiet,
  crowded, imperfect, or technically weak if it tells the truth of the moment.
- **Authorial meaning is separate from presentation.** A writer chooses a
  photograph, caption, relationship, and broad role such as `standard`,
  `large`, `full`, or `pair`; the renderer handles pixels and responsive layout.
- **The reader's page should be quiet.** Typography, prose, photographs,
  captions, and restrained links should carry the experience, without feeds,
  engagement counters, or interface chrome.
- **The writer owns the durable artifacts.** Stories are plain text and
  original photographs stay where the photographer keeps them. SQLite indexes
  and image caches are useful but reproducible.
- **Use ordinary standards where they already work.** Markdown handles prose
  and links; HTML and CSS handle publication; the `.story` format adds only the
  small photographic vocabulary Markdown lacks.
- **Keep authoring local and publishing boring.** The authoring tool may use a
  database, EXIF metadata, search, and previews. The published result remains
  static HTML, CSS, and images that can be hosted almost anywhere.
- **Do not accidentally rebuild Lightroom, WordPress, or a social network.** A
  feature belongs here only when it helps a writer tell a photographic story.

## Install

Python 3.10 or newer is required. In a virtual environment:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

With Nix, the included flake supplies Python 3.12, ExifTool, `uv`, all Python
dependencies, pytest, and the `story` command:

```sh
nix develop
story --help
pytest
```

You can also run or build the tool without entering the development shell:

```sh
nix run . -- --help
nix build
```

Once the repository is published, install the command into your Nix profile to
use it from a writing directory without entering the software repository:

```sh
nix profile install github:lila/travel-story
```

[ExifTool](https://exiftool.org/) is optional but recommended, especially for
RAW files and camera-specific metadata. If it is absent, Travel Story falls
back to Pillow for common image formats and basic EXIF fields.

## Quickstart

```sh
mkdir my-travels && cd my-travels
story init
story photos add ~/Pictures/Yellowstone
story photos search "Yellowstone"
story photos
```

The last command opens a local browser light table. Click a photo ID to copy it,
then place it in a story:

```text
---
title: Yellowstone
date: August 16–22, 2026
---

# Yellowstone

We reached the valley before sunrise.

@photo 7f23a1c92e04
layout: large
caption: A lone bison just after sunrise.

## August 18 — Mammoth

@photos 921ace0f22aa 125aa8d30211
layout: pair
relationship: sequence
caption: The terraces before and after the sun reached them.
```

### Apple Photos albums

On macOS, index an album directly without exporting or duplicating originals:

```sh
nix develop
story photos add-album "Yellowstone"
```

Album access currently uses the external `osxphotos` command when it is
available. Nixpkgs marks that package broken on macOS because required PyObjC
framework packages are missing, so the project flake deliberately does not try
to build it. Instead, install the upstream Python package once with the helper
provided by the development shell:

```sh
nix develop
story-install-osxphotos
osxphotos --version
```

The helper uses `uv` and Nix's Python 3.13, but installs OSXPhotos in uv's
per-user tool area rather than in the Nix store. The development shell adds
that tool area to `PATH`; after the one-time installation, leave and re-enter
`nix develop` if your current shell has not picked up `osxphotos` yet.

With `osxphotos` on your `PATH`, Travel Story hashes and catalogs originals in
place and creates only its normal disposable thumbnail and preview cache. It
does not modify the Photos library. A native PhotoKit bridge is planned to
remove this external dependency.

macOS may ask for Photos or Full Disk Access the first time. If originals are
stored only in iCloud, open or download them in Photos and run the command again.
To use a library other than the last-opened Photos library:

```sh
story photos add-album "Yellowstone" \
  --library ~/Pictures/Other\ Library.photoslibrary
```

Preview while writing, then build:

```sh
story preview yellowstone.story
story build yellowstone.story
```

Saving the file refreshes the preview. When a `site.toml` exists above the
story, a single-story build preserves the source path inside the site's
configured output: `yellowstone/trip1.story` becomes
`public/yellowstone/trip1/index.html`. Without a `site.toml`, the standalone
fallback remains `<trip>/public/trip1/index.html`. An explicit `--output`
always takes precedence.
Photographs in a story are clickable. Each opens a quiet, static photo page
showing its stable photo ID and available camera, lens, exposure, capture-time,
and dimension metadata. Captions remain part of their story placement; they are
not repeated as permanent photo metadata. Local file paths, camera originals,
and GPS coordinates are never published.

### Build the complete site

Keep the software repository separate from the writing publication. A typical
publication lives at `~/karans-stories` and gives each trip its own photo
catalog:

```text
~/karans-stories/
  site.toml
  yellowstone/
    .story/
      catalog.sqlite3
      cache/
    prologue.story
    yellowstone.story
  san-diego/
    .story/
      catalog.sqlite3
      cache/
    beaches.story
```

The top-level `site.toml` describes the homepage and the order of its source
stories:

```toml
title = "The Karan Family Travels"
description = "Photographic stories from the road."
output = "public"

stories = [
  "yellowstone/prologue.story",
  "yellowstone/yellowstone.story",
]
```

Build every listed story and the table-of-contents homepage with:

```sh
story site build
```

`story site build` searches the current directory and its parents for the
nearest `site.toml`. It can therefore be run from `~/karans-stories` or from a
trip directory beneath it. From elsewhere, specify the file explicitly:

```sh
story site build --config ~/karans-stories/site.toml
```

The complete site is replaced as one build, so an error cannot leave a mixture
of old and new pages. The result has ordinary static files and directories:

```text
public/
  index.html
  style.css
  yellowstone/
    prologue/
      index.html
      images/
      photos/
    yellowstone/
      index.html
      images/
      photos/
```

The story's relative source path supplies its URL: `yellowstone/prologue.story`
becomes `public/yellowstone/prologue/`. Its front matter supplies the title,
subtitle, and date shown on the homepage. The homepage groups stories by their
source directory, so both Yellowstone stories appear together under a
“Yellowstone” collection heading.
The source directories retain their `.story` files and local photo catalogs;
all generated publication artifacts go only into the top-level `public/`.
During a complete build, each story uses the nearest `.story` catalog above its
source file. Yellowstone and San Diego therefore remain independent photo
libraries even though one `site.toml` publishes them together.

### Check and maintain a story

Run a preflight before publishing:

```sh
story check yellowstone.story
```

The check reports unknown or ambiguous photo IDs, invalid layouts, missing
originals, and missing cached images. It does not modify the story or catalog.

Thumbnail and preview caches are disposable. Rebuild every cached image, or
only selected photo IDs, from the cataloged originals:

```sh
story photos rebuild-cache
story photos rebuild-cache 7f23a1c92e04 921ace0f22aa
```

Set attribution that belongs to the photo asset rather than to one story
placement:

```sh
story photos set 7f23a1c92e04 \
  --credit "Photograph by Karan" \
  --source-url "https://example.com/photos/7f23a1c92e04"
```

Credit and source are shown on the photo's detail page. Supplying an empty
value clears that field. Story captions remain in the `.story` file. Builds
replace the named story's existing output directory, so removed photographs do
not leave stale generated pages or image files behind.

## Story format

The optional front matter is a deliberately small `key: value` format. `title`,
`subtitle`, and `date` are displayed; other values are preserved for future
renderers. The body is Markdown. Photo directives occupy their own line:

- `@photo ID` places one photograph.
- `@photos ID ID ...` places a related group.
- Immediately following `layout: standard|large|full|pair` chooses presentation.
- Immediately following `caption: ...` adds a caption.
- `relationship: sequence|comparison|collection` records authorial intent. V1
  preserves it in the parsed story; layout remains explicitly controlled.

IDs may be unambiguous prefixes of the displayed 12-character ID.

## Architecture and ownership

Running `story init` creates:

```text
.story/
  catalog.sqlite3
  cache/
    thumbnails/
    previews/
```

The SQLite catalog stores paths, a SHA-256 content identity, EXIF metadata, and
optional asset-level credit/source information, and an FTS5 search index.
Originals remain exactly where the photographer put them; `photos add` reads
but never moves or rewrites them. If a file is relocated and added again, its
content hash reconnects it to the same ID. Cache files and the catalog are
reproducible authoring data. `.story` files and originals are the things you
own.

The browser servers use Python's standard library and bind to localhost by
default. Published output contains no Python, SQLite, server, or JavaScript.

Current search covers filenames, paths, descriptions, and keywords. Automatic
visual search, reverse geocoding, tagging commands, and library management are
intentionally outside V1.

## Development

```sh
python -m pip install -e . pytest
pytest
```
