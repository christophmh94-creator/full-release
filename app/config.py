import os

import yaml

DEFAULTS = {
    "server": {"host": "0.0.0.0", "port": 8080},
    # Folders the file browser is allowed to read (inside the container).
    "media_roots": ["/media"],
    # Where generated torrents / images / bbcode are written (inside the container).
    "output_dir": "/output",
    # Cove instance Full Release pulls metadata from (replaces the old Stash block).
    "cove": {"url": "", "username": "", "password": "", "api_key": ""},
    "torrent": {"announce_url": "", "source": "", "private": True},
    # Where single-file release folders are built. Keep this OUTSIDE Cove's
    # scanned library paths so hardlinked releases are not re-indexed as dupes.
    "packaging": {"dir": ""},  # empty -> "<first media_root>/_full-release"
    "contactsheet": {
        "columns": 4,
        "rows": 5,
        "thumb_width": 480,
        "header": True,
        "previews": 2,
    },
    "imagehost": {
        "provider": "chevereto",
        "chevereto_url": "",
        "chevereto_api_key": "",
        "nsfw": True,
        "imgbb_api_key": "",
    },
    "bbcode": {"include_performers": True, "template": "app/templates/release.bbcode.j2"},
}

EXAMPLE_YAML = """# Full Release configuration
# Edit this file, then restart the container.

server:
  host: 0.0.0.0
  port: 8080

# Folders inside the container the file browser may read.
# These map to the volumes you mount (default: /media -> your library, read-only).
media_roots:
  - /media

# Generated .torrent / contact sheet / bbcode are written here.
output_dir: /output

cove:
  # Your Cove instance, reachable from inside this container. Use the host LAN IP,
  # not 'localhost' (e.g. http://192.168.1.10:5073).
  url: "http://192.168.1.10:5073"
  # Cove login. If your Cove has auth enabled (COVE__Auth__Enabled=true) set these,
  # OR provide a pre-issued token as api_key below instead.
  username: ""
  password: ""
  # Optional: a pre-issued Cove bearer token. If set, username/password are ignored.
  # You can leave this blank and set the COVE_API_KEY environment variable instead.
  api_key: ""

torrent:
  # Your personal tracker announce URL (contains your passkey). Required for a usable torrent.
  announce_url: ""
  # Source flag written into the torrent. Luminance trackers check this against the site's
  # own configured short name (Torrent.php: make_unique()) - get it wrong and the site
  # silently rewrites it and asks you to re-download (info hash changes). Match it exactly.
  source: ""
  private: true

# Single-file selections are packaged into a release folder (<name>/<file> +
# <name>/screens/<contact sheet>) and the torrent covers that folder. The file is
# HARDLINKED in (original stays put; no extra disk), falling back to a move only if
# a hardlink across disks isn't possible. Keep this directory OUTSIDE Cove's scanned
# library so the hardlinked copy isn't re-indexed as a duplicate.
packaging:
  # Empty -> "<first media_root>/_full-release" (e.g. /media/_full-release, i.e.
  # /mnt/user/torrent/_full-release on the host). Set an absolute container path to override.
  dir: ""

contactsheet:
  columns: 4
  rows: 5
  thumb_width: 480   # px per frame before tiling
  header: true       # draw a filename/spec banner on the sheet
  previews: 2        # number of standalone preview stills (the two img=500 slots)

imagehost:
  # "chevereto" -> upload to a Chevereto V4 instance. Several Luminance-based trackers
  #                approve specific Chevereto hosts, so this is the default provider.
  # "imgbb"     -> auto-upload to imgbb.com (set imgbb_api_key). Only if your tracker allows it.
  # "manual"    -> no upload; the BBCode gets REPLACE_WITH_HOSTED_URL/<name> placeholders
  #                you swap by hand after uploading the saved images yourself.
  provider: "chevereto"
  chevereto_url: "https://your-chevereto-host.example"
  # SECRET - keep this file private (don't commit it to a public repo). You can leave
  # this blank and set the CHEVERETO_API_KEY environment variable instead.
  chevereto_api_key: ""
  nsfw: true            # tag uploads NSFW (recommended for this content)
  imgbb_api_key: ""

bbcode:
  include_performers: true
  template: "app/templates/release.bbcode.j2"
"""


def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def config_path():
    return os.environ.get("CONFIG_PATH", "/config/config.yaml")


def ensure_config():
    """Write a commented example config on first run so the user has something to edit."""
    path = config_path()
    if os.path.exists(path):
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(EXAMPLE_YAML)
        print(f"[Full Release] Wrote starter config to {path} - edit it and restart.")
    except OSError as e:
        print(f"[Full Release] Could not write starter config to {path}: {e}")


def load_config():
    path = config_path()
    cfg = dict(DEFAULTS)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            user = yaml.safe_load(f) or {}
        cfg = _merge(DEFAULTS, user)

    # Environment overrides (handy for compose / quick tests).
    if os.environ.get("COVE_URL"):
        cfg["cove"]["url"] = os.environ["COVE_URL"]
    if os.environ.get("COVE_USERNAME"):
        cfg["cove"]["username"] = os.environ["COVE_USERNAME"]
    if os.environ.get("COVE_PASSWORD"):
        cfg["cove"]["password"] = os.environ["COVE_PASSWORD"]
    if os.environ.get("COVE_API_KEY"):
        cfg["cove"]["api_key"] = os.environ["COVE_API_KEY"]
    if os.environ.get("ANNOUNCE_URL"):
        cfg["torrent"]["announce_url"] = os.environ["ANNOUNCE_URL"]
    if os.environ.get("PACKAGE_DIR"):
        cfg["packaging"]["dir"] = os.environ["PACKAGE_DIR"]
    if os.environ.get("CHEVERETO_URL"):
        cfg["imagehost"]["chevereto_url"] = os.environ["CHEVERETO_URL"]
    if os.environ.get("CHEVERETO_API_KEY"):
        cfg["imagehost"]["chevereto_api_key"] = os.environ["CHEVERETO_API_KEY"]
    return cfg
