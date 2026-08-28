# Full Release

A self-hosted web tool that turns a local video **file or folder** into an upload
package for a **private tracker** (currently scoped to trackers running
[Luminance](https://github.com/empornium/luminance)). It:

1. Lets you browse and select a file/folder from your library.
2. Queries your **Cove** instance for title, description, performers, tags, and
   technical details.
3. Generates a private **.torrent** (with your tracker's announce URL + source flag).
4. Builds a **contact sheet** and standalone **preview stills** with `ffmpeg`.
5. Renders the **BBCode** from your template, ready to paste.

It runs as a single Docker container with its own web GUI - no database, no
separate services. It is **not** a `.plg` Unraid plugin: a container is far more
robust and maintainable, and still gets a WebUI button, icon, and volume
mappings via the included template.

---

## Documentation

- **[docs/DEPLOY.md](docs/DEPLOY.md)** - getting the container running (Unraid or
  docker compose), rebuilding correctly, and wiring up the optional Cove
  "Open in Full Release" button.
- **[docs/CONFIGURE.md](docs/CONFIGURE.md)** - full `config.yaml` reference,
  including the Luminance-specific hard limits (piece size, path length,
  source-flag matching) that are enforced in code, not just documented.
- **[docs/USAGE.md](docs/USAGE.md)** - the actual Select → Inspect → Package
  workflow, what each step does, and what to do with the output.

The short version: build the image, run the container, point it at a running
Cove instance and your tracker's announce URL, then use the web UI.

---

## Tracker compatibility

Currently built and verified against **Luminance** specifically (the codebase
a number of private trackers in that family run), not assumed. The BBCode
tag usage, the 8 MiB piece-size cap, the 128-character file-path limit, and
the source/private-flag auto-correction behavior were all checked directly
against Luminance's own source (`Legacy/classes/Text.php`,
`Legacy/classes/Torrent.php`, `Legacy/sections/upload/upload_handle.php`) -
see [docs/CONFIGURE.md](docs/CONFIGURE.md) for what that means in practice.
Other tracker software isn't supported yet; the config format has no
per-tracker profile concept, just one BBCode template and one set of torrent
settings at a time.

---

## Possible next iterations

- **Bulletproof Cove matching** via `oshash` (Cove's own hash) instead of
  filename + size.
- Per-scene multi-file handling (galleries / multi-part scenes) and batch packaging.
- Optional auto-swap of preview/sheet URLs if you later switch image hosts.
- Broader tracker support beyond Luminance-based trackers.

---

## Project layout

```
full-release/
├── Dockerfile
├── docker-compose.yml
├── unraid-template.xml
├── config.example.yaml
├── requirements.txt
├── README.md
├── docs/
│   ├── DEPLOY.md
│   ├── CONFIGURE.md
│   └── USAGE.md
├── app/
│   ├── main.py          FastAPI app + background job pipeline
│   ├── config.py        config load/merge + starter config
│   ├── cove.py          Cove REST client (match by basename + size)
│   ├── media.py         ffprobe + contact sheet / preview generation
│   ├── torrent.py       torrent creation (torf), Luminance piece-size/path-length limits
│   ├── imagehost.py     chevereto / imgbb / manual upload
│   ├── bbcode.py        Jinja2 BBCode renderer
│   └── templates/
│       ├── release.bbcode.j2         active template (black / orange)
│       └── release.bbcode.legacy.j2  previous version, kept for rollback
├── web/
│   └── index.html       single-file operator console (no build step)
├── branding/           logo assets (not used at runtime)
│   ├── full-release_wordmark.svg / .png          transparent, for dark backgrounds
│   ├── full-release_wordmark_black.svg / .png    on a black plate
│   └── full-release_icon.svg / _512.png / _1024.png   square app icon
└── previews/           design references (not used at runtime)
    └── release_template_preview.html   before/after of the BBCode layout
```

> A screenshot of the populated web UI used to live in `previews/` too. It was
> dropped rather than shipped stale: it still showed the pre-rename branding
> throughout, and regenerating it needs a browser against a running instance.
> Take a fresh one if you want it back.

Only `requirements.txt`, `app/` and `web/` are copied into the Docker image —
`branding/`, `previews/`, and `docs/` are reference material and don't affect
the build.

### Branding

The wordmark is `Full` in white next to `Release` in an orange box; the palette is
black `#000000` + orange `#FF9900`, matching the BBCode template and the web UI.
The header logo in the web UI is plain styled text (no vector artwork needed at
runtime).

The `branding/` assets are rendered with Pillow (DejaVu Sans Bold) rather than
outlined to font-independent vector paths. The `.svg` files are thin wrappers
around the same PNGs (a `<image>` element with the raster embedded as
base64), not true vector paths - functionally valid SVGs, but they won't
scale losslessly. Redoing these as real outlined vector art is a manual
follow-up if that matters for your use case.

For the Unraid container icon, point the template's `<Icon>` field at
`full-release_icon_512.png` (host it somewhere reachable, e.g. a GitHub raw URL).
