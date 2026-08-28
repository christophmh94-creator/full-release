# Configuring Full Release

For getting the container running in the first place, see
[DEPLOY.md](DEPLOY.md). For the actual workflow once it's configured, see
[USAGE.md](USAGE.md).

On first run, Full Release writes a commented starter `config.yaml` to
`/config` (see `app/config.py`'s `EXAMPLE_YAML` for the exact text it
writes). Edit that file and **recreate the container** to pick up changes -
a `docker restart` is enough for config changes specifically (unlike image
rebuilds, which need a full recreate - see DEPLOY.md).

Every setting can also be set via environment variable, which overrides the
matching `config.yaml` key. That's the more convenient path from a Docker
Compose file or an Unraid template.

---

## `cove` - where metadata comes from

| Key | Env var | Required | What |
|---|---|---|---|
| `cove.url` | `COVE_URL` | **Yes** | Your Cove instance, reachable from *inside the container*. Use the LAN IP, not `localhost` - Cove and Full Release are separate containers even if they're on the same host. |
| `cove.username` / `cove.password` | `COVE_USERNAME` / `COVE_PASSWORD` | If Cove auth is enabled | Full Release logs in via `POST /api/auth/login` and reuses the session cookie for subsequent calls. |
| `cove.api_key` | `COVE_API_KEY` | Alternative to the above | A pre-issued Cove bearer token. If set, it's sent as `Authorization: Bearer …` and username/password are ignored. |

Without a working Cove connection, the Inspect step still works - you just
get a manual entry form instead of an auto-filled match.

---

## `torrent` - the actual upload artifact

| Key | Env var | Required | What |
|---|---|---|---|
| `torrent.announce_url` | `ANNOUNCE_URL` | **Yes**, for a usable torrent | Your personal announce URL, passkey included. |
| `torrent.source` | - | Effectively yes | The source flag baked into the torrent. **This has to match your tracker's exact configured short name.** On Luminance-based trackers this is checked server-side (`Torrent.php: make_unique()`) - get it wrong and the site doesn't reject the upload, it silently *rewrites* the source flag and tells you to re-download the torrent, because the correction changes the info hash. Blank by default; there's no universal correct value. |
| `torrent.private` | - | Leave `true` | The private flag. Luminance also auto-corrects this if unset, same story as `source` - always leave it `true` unless you have a specific reason not to. |

### Hard limits enforced by Full Release itself

These come from reading Luminance's actual upload validation
(`Torrent.php: use_strict_bencode_specification()`), not guesswork - see the
project's commit history / notes if you want the full trace:

- **Piece size capped at 8 MiB.** torf's own default algorithm can pick up
  to 16 MiB pieces for very large releases (>16 GiB), which Luminance
  rejects outright (not auto-corrected, a hard `error()`). Full Release
  always caps at 8 MiB, so large releases just end up with more, still
  correctly-sized pieces - there's no release-size limit from this, only a
  piece-size one.
- **Per-file path length capped at 128 characters.** Luminance also hard-
  rejects any file whose path *inside the torrent* (not counting the
  top-level release folder name) is longer than that. Full Release doesn't
  truncate anything automatically - it surfaces a warning in the package
  result if a file would trip this, so you can rename before uploading
  instead of finding out from a rejected upload.

---

## `packaging` - where single-file releases get built

| Key | Env var | Default | What |
|---|---|---|---|
| `packaging.dir` | `PACKAGE_DIR` | `<first media_root>/_full-release` | Where single-file selections get their release folder built: `<name>/<file>` plus `<name>/screens/<contact sheet>`. The original file is **hardlinked** in (no extra disk use, original stays where it was), falling back to a move only if hardlinking across disks isn't possible. |

Keep this directory **outside** whatever Cove actually scans as your
library, or the hardlinked copy shows up as a duplicate in Cove.

---

## `contactsheet`

| Key | Default | What |
|---|---|---|
| `contactsheet.columns` | `4` | Grid columns in the tiled contact sheet. |
| `contactsheet.rows` | `5` | Grid rows. |
| `contactsheet.thumb_width` | `480` | Pixels per frame before tiling. |
| `contactsheet.header` | `true` | Draw a filename/spec banner on the sheet. |
| `contactsheet.previews` | `2` | Number of standalone preview stills generated alongside the tiled sheet. |

Columns/rows are also editable per-package in the Inspect step, so the
config values are just the default.

---

## `imagehost` - where screenshots get uploaded

| Key | Env var | What |
|---|---|---|
| `imagehost.provider` | - | `chevereto` (default), `imgbb`, or `manual`. |
| `imagehost.chevereto_url` | `CHEVERETO_URL` | Base URL of a Chevereto V4 instance. Nothing is pre-filled - point this at whatever host your tracker actually approves. |
| `imagehost.chevereto_api_key` | `CHEVERETO_API_KEY` | **Secret.** Chevereto API key, sent as `X-API-Key`. Keep `config.yaml` private if you set it there instead of the env var. |
| `imagehost.imgbb_api_key` | - | Only used if `provider: imgbb`. Confirm imgbb is actually acceptable on your tracker before relying on it. |
| `imagehost.nsfw` | - | `true` by default; tags Chevereto uploads NSFW. |

**`manual` mode** does no uploading at all - images are only written to
`/output`, and the BBCode gets `REPLACE_WITH_HOSTED_URL/<filename>`
placeholders you swap by hand after uploading them yourself. Useful if your
tracker doesn't approve any host Full Release talks to directly.

---

## `bbcode`

| Key | Default | What |
|---|---|---|
| `bbcode.template` | `app/templates/release.bbcode.j2` | Path to the Jinja2 template rendered for the final BBCode box. `release.bbcode.legacy.j2` is kept alongside it for rollback. |
| `bbcode.include_performers` | `true` | Whether to render the "Starring" line from Cove's performer list. |

The shipped template's tag usage (`[align]`, `[size=0-10]`, hex `[color]`,
`[bg]`, `[table]/[tr]/[td]`, `[img=WIDTH]`) was checked directly against
Luminance's BBCode parser (`Legacy/classes/Text.php`), not assumed. If you
write your own template for a different tracker's dialect, that's the file
whose parsing rules you need to match.

---

## `media_roots` / `output_dir` / `server`

| Key | Env var | What |
|---|---|---|
| `media_roots` | - | List of folders the file browser may read (inside the container). Must line up with your volume mounts - see DEPLOY.md. |
| `output_dir` | - | Where generated `.torrent` / contact sheet / BBCode files land, inside the container. |
| `server.host` / `server.port` | - | Almost never needs changing; the container's internal listen address. Map the *host* port via Docker (`-p 8008:8080`), don't change this. |

---

## Keeping secrets out of version control

`config.yaml` can contain your tracker passkey and your image host API key.
Don't commit it anywhere public. If you're sharing this deployment or
scripting it, prefer the env var overrides (`ANNOUNCE_URL`,
`CHEVERETO_API_KEY`, etc.) over writing secrets into the YAML file, and treat
`config.example.yaml` in this repo as a template with no real values in it -
if you ever see a real key in that file, that's a mistake, not an example.
