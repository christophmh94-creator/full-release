# Using Full Release

Assumes you've already got it deployed ([DEPLOY.md](DEPLOY.md)) and
configured with a working Cove connection ([CONFIGURE.md](CONFIGURE.md)).
This is the actual workflow, end to end.

Everything here assumes **Cove** as the metadata source - that's the only
scraper backend Full Release currently talks to.

---

## The three steps

The web UI is one page, laid out as a pipeline: **Select → Inspect →
Package**. Each step unlocks the next.

### 1. Select

Two ways in:

**From Cove, if the "Open in Full Release" button is set up** (see
DEPLOY.md) - open a video's page in Cove, click it, and a new tab opens
straight into step 2 with the file already selected and Cove already
queried. This is the fast path and the one this project assumes you'll use
most.

**From the file browser directly** - the built-in browser is restricted to
your configured `media_roots`. Pick a single video file, or open a folder
and hit **Select this folder**.

- Selecting a **single file**: it gets packaged into a release folder named
  after the file. The original is hardlinked in (moved only if hardlinking
  isn't possible across disks) - your source file doesn't move on disk in
  the normal case, but its *path* does change to the new release folder, so
  if Cove is scanning that library, rescan it afterward.
- Selecting a **folder**: the whole folder is torrented as-is, no file
  moves.

There's a filter box above the list - type to filter the current folder
live, or hit **Enter** to run a deeper search across the whole library from
that point down.

### 2. Inspect

Hit **Inspect selection**. Full Release probes the file with `ffprobe` for
technical details, then tries to match it in Cove by **filename + file
size** (not the absolute path - Cove and Full Release usually see different
mount points for the same file).

Three outcomes:

- **Matched** - one exact hit. Title, description, performers, and specs
  are pulled straight from Cove and pre-filled.
- **Several matches** - a dropdown to pick the right one.
- **No match** - a manual search box against Cove (by title/performer), or
  just fill every field in by hand.

Every field is editable regardless of match status - this is the point to
fix a title Cove doesn't have quite right, trim the description, or correct
the performer list before it ends up in the BBCode. Sheet columns/rows can
also be overridden here per-release without touching `config.yaml`.

If you picked the wrong match or want to try a different one, there's a
**change** link that reopens the search box; re-running Inspect after
picking a different scene is called **Re-inspect** once you've already got a
result.

### 3. Package

Hit **Build torrent, contact sheet & BBCode**. This runs as a background job
with a live progress bar through several stages:

1. **Assembling release folder** (single-file selections only) - the
   hardlink/move step described above.
2. **Hashing torrent** - creates the `.torrent`, private flag set, source
   flag from config, piece size capped at 8 MiB (see CONFIGURE.md for why).
3. **Contact sheet & previews** - `ffmpeg` builds the tiled contact sheet and
   standalone preview stills. For a folder selection, these come from the
   **largest video file** in the folder, not the whole folder's contents.
4. **Uploading images** - to whichever `imagehost.provider` is configured.
   Skipped (placeholders only) in `manual` mode.
5. **BBCode** - rendered from the configured Jinja2 template with everything
   gathered above.

### The result

- Download buttons for the `.torrent` and a `.bbcode.txt`.
- A preview of the contact sheet (and an animated GIF preview, if one was
  generated).
- A **tracker tags line** - a ready-to-paste string combining Cove's tags,
  resolution, and performer names, meant for the tracker's separate tag
  input field (not the BBCode body).
- Direct links to every uploaded image, individually and as a copy-all
  block.
- The full **BBCode box**, one click to copy, ready to paste into your
  tracker's upload form.
- Any **warnings** - hardlink fallback, image upload failures, or a file
  path too long for the tracker (see CONFIGURE.md's hard-limits section).
  None of these block the package from completing; they're things to check
  before you actually submit the upload.

Everything lands under `/output/<name>/` inside the container. You can hit
**Re-package** afterward (e.g. after editing a field and re-inspecting)
without starting over from Select.

---

## What actually goes to the tracker

Full Release doesn't submit anything itself - there's no tracker API
integration. The output is three things you paste/upload manually into your
tracker's own upload form:

1. The `.torrent` file.
2. The BBCode, into the description field.
3. The tags line, into the tags field.

If your tracker corrects the torrent's `source` or `private` flag on
upload (Luminance-based trackers do this silently when they don't match),
**download the corrected torrent from the tracker before seeding** - the
info hash changed, and the one Full Release generated won't match what
other peers are seeding.

---

## Re-running things

- **Re-inspect**: change the file, or want a different Cove match - just hit
  Inspect again (now labeled Re-inspect) from step 2. This doesn't lose your
  edits to the other fields.
- **Re-package**: after any edit, hit the package button again. If the
  release folder already exists from a previous run, it's reused rather than
  duplicated.
- Nothing here is destructive to your source media beyond the one hardlink/
  move step in Select - re-running Package repeatedly on the same selection
  doesn't move anything a second time.
