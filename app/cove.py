"""Cove REST client.

Drop-in replacement for the old Stash GraphQL client. Talks to a Cove instance
(https://github.com/yourcove/cove) over its REST API and normalises each video
into the *same* dict shape the rest of Full Release already expects, so main.py /
media.py / the BBCode templates did not need to change their field access:

    {
      "id": str, "title": str, "date": str|None, "details": str,
      "studio": {"name": str}|None,
      "performers": [{"name": str}, ...],
      "tags": [{"name": str}, ...],
      "files": [{"path","basename","size","duration","width","height",
                 "video_codec","audio_codec","frame_rate","bit_rate","format"}, ...],
    }

Matching strategy is unchanged from the Stash version: the path Cove sees for a
file usually differs from the path this container sees (different mounts), so we
match on the *basename* (filename) and confirm with file size, not the path.

Auth: Cove uses cookie/session auth via POST /api/auth/login and also accepts a
Bearer token. We use a requests.Session so the login cookie carries subsequent
calls; if login also returns a token we set it as a Bearer header too. A
pre-issued token can be supplied instead of username/password (cove.api_key).
"""
import requests

# Candidate field names Cove may use. We read the first present one so small
# naming differences between Cove versions don't break the mapping. Exact names
# are confirmed against the live instance during porting.
_TITLE = ("title", "name")
_DETAILS = ("details", "description", "summary")
_DATE = ("date", "releaseDate", "released", "createdAt")
_STUDIO = ("studio", "studioName")
_PERFORMERS = ("performers", "actors", "people")
_TAGS = ("tags", "labels")
_FILES = ("files", "videoFiles", "mediaFiles")
_PATH = ("path", "fullPath", "filePath", "location")
_BASENAME = ("basename", "fileName", "filename", "name")
_SIZE = ("size", "fileSize", "sizeBytes", "bytes")
_DURATION = ("duration", "durationSeconds", "runtime", "seconds")
_WIDTH = ("width", "videoWidth")
_HEIGHT = ("height", "videoHeight")
_VCODEC = ("videoCodec", "video_codec", "vcodec")
_ACODEC = ("audioCodec", "audio_codec", "acodec")
_FPS = ("frameRate", "frame_rate", "fps")
_BITRATE = ("bitRate", "bit_rate", "bitrate")
_FORMAT = ("container", "format", "ext", "extension")


class CoveError(Exception):
    pass


def _first(obj, keys, default=None):
    if not isinstance(obj, dict):
        return default
    for k in keys:
        if k in obj and obj[k] not in (None, ""):
            return obj[k]
    return default


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _name_list(items):
    """Cove may return performers/tags as list of strings or list of objects."""
    out = []
    for it in items or []:
        if isinstance(it, str):
            out.append({"name": it})
        elif isinstance(it, dict):
            out.append({"name": _first(it, ("name", "title"), "")})
    return out


class CoveClient:
    def __init__(self, url, api_key=None, username=None, password=None, timeout=20):
        self.url = url.rstrip("/")
        self.api = f"{self.url}/api"
        self.timeout = timeout
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/json"
        if api_key:
            self.session.headers["Authorization"] = f"Bearer {api_key}"
        self._logged_in = bool(api_key)

    # -- auth ---------------------------------------------------------------- #
    def _login(self):
        if not (self.username and self.password):
            raise CoveError("Cove auth required: set cove.username/password or cove.api_key")
        last = None
        for body in (
            {"username": self.username, "password": self.password},
            {"email": self.username, "password": self.password},
        ):
            try:
                r = self.session.post(f"{self.api}/auth/login", json=body, timeout=self.timeout)
            except requests.RequestException as e:
                raise CoveError(f"Could not reach Cove: {e}") from e
            last = r.status_code
            if r.status_code < 400:
                token = None
                try:
                    token = _first(r.json(), ("token", "accessToken", "access_token", "jwt"))
                except ValueError:
                    pass
                if token:
                    self.session.headers["Authorization"] = f"Bearer {token}"
                self._logged_in = True
                return
        raise CoveError(f"Cove login failed (HTTP {last})")

    def _get(self, path, params=None, _retry=True):
        if not self._logged_in:
            self._login()
        try:
            r = self.session.get(f"{self.api}{path}", params=params, timeout=self.timeout)
        except requests.RequestException as e:
            raise CoveError(f"Could not reach Cove: {e}") from e
        if r.status_code == 401 and _retry and self.username:
            self._logged_in = False
            self._login()
            return self._get(path, params, _retry=False)
        if r.status_code >= 400:
            raise CoveError(f"Cove returned HTTP {r.status_code} for {path}")
        try:
            return r.json()
        except ValueError as e:
            raise CoveError(f"Cove returned non-JSON for {path}") from e

    @staticmethod
    def _items(payload):
        """List endpoints may wrap as {items:[]},{data:[]},{results:[]} or a bare list."""
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for k in ("items", "data", "results", "videos"):
                if isinstance(payload.get(k), list):
                    return payload[k]
        return []

    # -- normalisation ------------------------------------------------------- #
    def _map_file(self, f):
        return {
            "path": _first(f, _PATH, ""),
            "basename": _first(f, _BASENAME, ""),
            "size": _to_int(_first(f, _SIZE)),
            "duration": _first(f, _DURATION),
            "width": _first(f, _WIDTH),
            "height": _first(f, _HEIGHT),
            "video_codec": _first(f, _VCODEC),
            "audio_codec": _first(f, _ACODEC),
            "frame_rate": _first(f, _FPS),
            "bit_rate": _first(f, _BITRATE),
            "format": _first(f, _FORMAT),
        }

    def _map_video(self, v):
        if not isinstance(v, dict):
            return None
        files = _first(v, _FILES)
        if isinstance(files, dict):
            files = [files]
        if not files:
            files = [v]  # some builds put file info flat on the video object
        studio = _first(v, _STUDIO)
        if isinstance(studio, str):
            studio = {"name": studio}
        elif isinstance(studio, dict):
            studio = {"name": _first(studio, ("name", "title"), "")}
        return {
            "id": str(_first(v, ("id", "videoId", "uuid"), "")),
            "title": _first(v, _TITLE, ""),
            "date": _first(v, _DATE),
            "details": _first(v, _DETAILS, ""),
            "studio": studio,
            "performers": _name_list(_first(v, _PERFORMERS, [])),
            "tags": _name_list(_first(v, _TAGS, [])),
            "files": [self._map_file(f) for f in files],
        }

    # -- public API (mirrors the old StashClient) --------------------------- #
    def test(self):
        """Confirm the instance is reachable AND credentials work; return a
        short version/label string for the status pill."""
        self._get("/videos", {"perPage": 1, "page": 1})
        try:
            ver = self._get("/system/version")
            if isinstance(ver, dict):
                return _first(ver, ("version", "appVersion"), "connected")
            if isinstance(ver, str):
                return ver
        except CoveError:
            pass
        return "connected"

    def find_scenes_by_basename(self, basename, size=None):
        payload = self._get("/videos", {"q": basename, "perPage": 25, "page": 1})
        videos = [v for v in (self._map_video(x) for x in self._items(payload)) if v]

        def is_exact(v):
            for vf in v.get("files", []):
                if vf.get("basename") == basename:
                    if size is None or vf.get("size") == int(size):
                        return True
            return False

        exact = [v for v in videos if is_exact(v)]
        return exact or videos

    def get_cover(self, video_id):
        """Download the video's cover/thumbnail image bytes from Cove (or None).
        Cove serves a generated cover at /api/videos/{id}/image even when the JSON
        `imagePath` is null."""
        if not video_id:
            return None
        if not self._logged_in:
            self._login()
        url = f"{self.api}/videos/{video_id}/image"
        try:
            r = self.session.get(url, timeout=self.timeout)
            if r.status_code == 401 and self.username:
                self._logged_in = False
                self._login()
                r = self.session.get(url, timeout=self.timeout)
        except requests.RequestException:
            return None
        if r.status_code >= 400:
            return None
        if not (r.headers.get("Content-Type", "").startswith("image/")):
            return None
        return r.content or None

    def find_scene_by_id(self, scene_id):
        return self._map_video(self._get(f"/videos/{scene_id}"))

    def search_scenes(self, term):
        payload = self._get("/videos", {"q": term, "perPage": 25, "page": 1})
        return [v for v in (self._map_video(x) for x in self._items(payload)) if v]
