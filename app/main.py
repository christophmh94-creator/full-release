import os
import shutil
import threading
import traceback
import uuid
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from . import bbcode, imagehost, media
from . import torrent as torrent_mod
from .config import ensure_config, load_config
from .cove import CoveClient, CoveError

ensure_config()
CFG = load_config()

APP_DIR = os.path.dirname(__file__)
ROOT_DIR = os.path.dirname(APP_DIR)
WEB_DIR = os.path.join(ROOT_DIR, "web")
OUTPUT_DIR = CFG.get("output_dir", "/output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

VIDEO_EXTS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".m4v", ".flv",
    ".ts", ".webm", ".mpg", ".mpeg", ".m2ts", ".vob",
}

app = FastAPI(title="Full Release")

jobs = {}
jobs_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def cove_client():
    s = CFG.get("cove", {})
    if not s.get("url"):
        return None
    return CoveClient(
        s["url"],
        api_key=s.get("api_key") or None,
        username=s.get("username") or None,
        password=s.get("password") or None,
    )


def _imagehost_host():
    """Friendly host label for the status pill (the actual host, not the software)."""
    ih = CFG.get("imagehost", {})
    provider = (ih.get("provider") or "manual").lower()
    if provider == "chevereto":
        netloc = urlparse(ih.get("chevereto_url") or "").netloc
        return netloc or "chevereto"
    if provider == "imgbb":
        return "imgbb.com"
    return "manual"


def _imagehost_ready():
    """True if the configured auto-upload provider has the credentials it needs."""
    ih = CFG.get("imagehost", {})
    provider = (ih.get("provider") or "manual").lower()
    if provider == "chevereto":
        return bool(ih.get("chevereto_url") and ih.get("chevereto_api_key"))
    if provider == "imgbb":
        return bool(ih.get("imgbb_api_key"))
    return False  # manual is never "ready" - it produces placeholders


def safe_path(p):
    roots = [os.path.realpath(r) for r in CFG.get("media_roots", [])]
    rp = os.path.realpath(p)
    for root in roots:
        if rp == root or rp.startswith(root + os.sep):
            return rp
    raise HTTPException(status_code=400, detail="Path is outside the allowed media roots")


def pick_video_file(path):
    """Selection may be a folder; choose the largest video file within it."""
    if os.path.isfile(path):
        return path
    best, best_size = None, -1
    for dirpath, _dirs, files in os.walk(path):
        for fn in files:
            if os.path.splitext(fn)[1].lower() in VIDEO_EXTS:
                full = os.path.join(dirpath, fn)
                try:
                    sz = os.path.getsize(full)
                except OSError:
                    continue
                if sz > best_size:
                    best, best_size = full, sz
    return best


def match_summary(s):
    files = s.get("files") or [{}]
    return {
        "id": s.get("id"),
        "title": s.get("title") or os.path.basename(files[0].get("path", "")),
        "date": s.get("date"),
        "studio": (s.get("studio") or {}).get("name"),
        "basename": files[0].get("basename"),
    }


def scene_to_meta(scene, video, info):
    ext = os.path.splitext(video)[1].lstrip(".").upper()
    file_type = ext or (info.get("format", "").upper() or "MP4")
    size = info.get("size", 0)
    duration = info.get("duration", 0)
    width, height = info.get("width"), info.get("height")
    title = os.path.splitext(os.path.basename(video))[0]
    details, performers = "", ""

    if scene:
        if scene.get("title"):
            title = scene["title"]
        details = scene.get("details") or ""
        performers = ", ".join(p["name"] for p in (scene.get("performers") or []))
        vf = (scene.get("files") or [{}])[0]
        if vf.get("width"):
            width = vf["width"]
        if vf.get("height"):
            height = vf["height"]
        if vf.get("duration"):
            duration = vf["duration"]
        if vf.get("size"):
            try:
                size = int(vf["size"])
            except (TypeError, ValueError):
                pass

    return {
        "title": title,
        "details": details,
        "performers": performers,
        "file_type": file_type,
        "file_size": media.human_size(size),
        "duration": media.fmt_duration(duration),
        "resolution": f"{width}x{height}",
    }



import re as _re


def _norm_tag(text):
    """tracker-style token: lowercase, non-alphanumeric runs -> '.', trimmed."""
    t = _re.sub(r"[^a-z0-9]+", ".", (text or "").lower()).strip(".")
    return t


def _resolution_label(info, fallback=""):
    """Height -> 2160p/1080p/720p... Falls back to parsing a 'WxH' string."""
    h = 0
    try:
        h = int(info.get("height") or 0)
    except (TypeError, ValueError, AttributeError):
        h = 0
    if not h and fallback:
        m = _re.search(r"(\d+)\s*[xX]\s*(\d+)", str(fallback))
        if m:
            h = int(m.group(2))
    if not h:
        return ""
    known = {2160: "2160p", 1440: "1440p", 1080: "1080p", 720: "720p",
             576: "576p", 540: "540p", 480: "480p", 360: "360p", 240: "240p"}
    if h in known:
        return known[h]
    # snap to nearest common bucket by width-agnostic height
    for k in sorted(known, reverse=True):
        if h >= k:
            return known[k]
    return f"{h}p"


def build_tag_line(cove_tags, res_label, performers):
    """Copy-paste tracker tag string: cove tags + resolution + performers,
    each normalised (spaces/punct -> dots), de-duplicated, space-separated."""
    parts = []
    for t in (cove_tags or []):
        parts.append(_norm_tag(t))
    if res_label:
        parts.append(_norm_tag(res_label))
    for p in (performers or []):
        parts.append(_norm_tag(p))
    seen, out = set(), []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return " ".join(out)


def set_job(job_id, **kw):
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(kw)


# --------------------------------------------------------------------------- #
# routes
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(WEB_DIR, "index.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/api/config")
def get_config():
    s = cove_client()
    cove_ok, cove_ver = False, None
    if s:
        try:
            cove_ver = s.test()
            cove_ok = True
        except CoveError:
            cove_ok = False
    return {
        "media_roots": CFG.get("media_roots", []),
        "cove_configured": bool(s),
        "cove_ok": cove_ok,
        "cove_version": cove_ver,
        "announce_set": bool(CFG.get("torrent", {}).get("announce_url")),
        "imagehost_provider": CFG.get("imagehost", {}).get("provider", "manual"),
        "imagehost_host": _imagehost_host(),
        "imagehost_ready": _imagehost_ready(),
        "contactsheet": CFG.get("contactsheet", {}),
    }


@app.get("/api/browse")
def browse(path: str = ""):
    roots = CFG.get("media_roots", [])
    if not path:
        return {
            "path": "",
            "parent": None,
            "is_root_list": True,
            "entries": [{"name": r, "path": r, "type": "dir"} for r in roots],
        }

    rp = safe_path(path)
    if not os.path.isdir(rp):
        raise HTTPException(status_code=400, detail="Not a directory")

    entries = []
    try:
        for name in sorted(os.listdir(rp), key=str.lower):
            full = os.path.join(rp, name)
            if os.path.isdir(full):
                entries.append({"name": name, "path": full, "type": "dir"})
            elif os.path.splitext(name)[1].lower() in VIDEO_EXTS:
                try:
                    size = os.path.getsize(full)
                except OSError:
                    size = 0
                entries.append({"name": name, "path": full, "type": "file", "size": size})
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    is_root = any(os.path.realpath(rp) == os.path.realpath(r) for r in roots)
    parent = None if is_root else os.path.dirname(rp)
    return {"path": rp, "parent": parent, "is_root_list": False, "entries": entries}


@app.get("/api/search")
def search_files(q: str, path: str = ""):
    """Recursive filename search across the media root (or a subfolder), so the
    user doesn't have to scroll. Time- and count-capped to stay responsive on
    very large libraries."""
    import time
    term = (q or "").strip().lower()
    if len(term) < 2:
        return {"entries": [], "capped": False}

    if path:
        roots = [safe_path(path)]
    else:
        roots = [os.path.realpath(r) for r in CFG.get("media_roots", [])]

    cap = 300
    deadline = time.time() + 6.0
    results, capped = [], False
    for root in roots:
        for dirpath, dirs, files in os.walk(root):
            if time.time() > deadline or len(results) >= cap:
                capped = True
                break
            for dn in sorted(dirs, key=str.lower):
                if term in dn.lower():
                    results.append({"name": dn, "path": os.path.join(dirpath, dn), "type": "dir"})
            for fn in sorted(files, key=str.lower):
                if os.path.splitext(fn)[1].lower() in VIDEO_EXTS and term in fn.lower():
                    full = os.path.join(dirpath, fn)
                    try:
                        size = os.path.getsize(full)
                    except OSError:
                        size = 0
                    results.append({"name": fn, "path": full, "type": "file", "size": size})
            if len(results) >= cap:
                capped = True
                break
        if time.time() > deadline or len(results) >= cap:
            capped = True
            break
    return {"entries": results[:cap], "capped": capped}


class AnalyzeReq(BaseModel):
    path: str
    scene_id: str | None = None


@app.post("/api/analyze")
def analyze(req: AnalyzeReq):
    rp = safe_path(req.path)
    video = pick_video_file(rp)
    if not video:
        raise HTTPException(status_code=400, detail="No video file found in the selection")

    info = media.ffprobe_info(video)
    scene, matches = None, []
    s = cove_client()
    if s:
        try:
            if req.scene_id:
                scene = s.find_scene_by_id(req.scene_id)
            else:
                found = s.find_scenes_by_basename(os.path.basename(video), info.get("size"))
                matches = found
                if len(found) == 1:
                    scene = found[0]
        except CoveError:
            matches = []

    return {
        "video": video,
        "is_folder": os.path.isdir(rp),
        "info": info,
        "scene": scene,
        "matches": [match_summary(m) for m in matches],
        "meta": scene_to_meta(scene, video, info),
    }


@app.get("/api/cove/search")
def cove_search(q: str):
    s = cove_client()
    if not s:
        return {"scenes": []}
    try:
        scenes = s.search_scenes(q)
    except CoveError as e:
        raise HTTPException(status_code=502, detail=f"Cove error: {e}")
    return {"scenes": [match_summary(x) for x in scenes]}


class GenerateReq(BaseModel):
    path: str
    scene_id: str | None = None
    title: str
    details: str = ""
    performers: str = ""
    file_type: str
    file_size: str
    duration: str
    resolution: str
    columns: int | None = None
    rows: int | None = None


@app.post("/api/generate")
def generate(req: GenerateReq):
    rp = safe_path(req.path)
    video = pick_video_file(rp)
    if not video:
        raise HTTPException(status_code=400, detail="No video file found in the selection")

    job_id = uuid.uuid4().hex
    with jobs_lock:
        jobs[job_id] = {
            "status": "running", "progress": 0, "stage": "Starting",
            "result": None, "error": None,
        }
    threading.Thread(
        target=run_generate, args=(job_id, rp, video, req), daemon=True
    ).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    with jobs_lock:
        j = jobs.get(job_id)
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    return j


@app.get("/api/file")
def get_file(path: str):
    rp = os.path.realpath(path)
    out = os.path.realpath(OUTPUT_DIR)
    if not (rp == out or rp.startswith(out + os.sep)):
        raise HTTPException(status_code=400, detail="File is outside the output directory")
    if not os.path.isfile(rp):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(rp, filename=os.path.basename(rp))


# --------------------------------------------------------------------------- #
# the packaging job
# --------------------------------------------------------------------------- #
def run_generate(job_id, selection, video, req):
    try:
        base = os.path.splitext(os.path.basename(video))[0]
        safe = "".join(c for c in base if c.isalnum() or c in " ._-").strip() or "release"
        workdir = os.path.join(OUTPUT_DIR, safe)
        os.makedirs(workdir, exist_ok=True)

        info = media.ffprobe_info(video)
        cs_cfg = CFG.get("contactsheet", {})
        cols = req.columns or cs_cfg.get("columns", 4)
        rows = req.rows or cs_cfg.get("rows", 5)

        # All image assets are generated from the ORIGINAL file first, because a
        # single-file selection then gets moved into a release folder below.

        # 1) contact sheet  (5-38%)
        set_job(job_id, stage="Building contact sheet", progress=6)
        cs_path = os.path.join(workdir, safe + "_contact.jpg")
        media.make_contact_sheet(
            video, info, cs_path,
            cols=cols, rows=rows,
            thumb_width=cs_cfg.get("thumb_width", 480),
            header=cs_cfg.get("header", True),
            progress=lambda d, t: set_job(job_id, progress=6 + int(d / t * 32)),
        )

        # 2) previews  (38-46%)
        set_job(job_id, stage="Extracting previews", progress=40)
        previews = media.make_previews(
            video, info, workdir, count=cs_cfg.get("previews", 2), base=safe
        )

        # 3b) Cove cover/thumbnail (if this file matched a Cove scene)
        cover_path = None
        cove_tags = []
        if req.scene_id:
            try:
                cc = cove_client()
                if cc:
                    scene_full = cc.find_scene_by_id(req.scene_id)
                    cove_tags = [t.get("name", "") for t in (scene_full or {}).get("tags", [])]
                    cbytes = cc.get_cover(req.scene_id)
                    if cbytes:
                        cover_path = os.path.join(workdir, safe + "_cover.jpg")
                        with open(cover_path, "wb") as cf:
                            cf.write(cbytes)
            except Exception:  # noqa: BLE001 - cover/tags are best-effort
                pass

        # 2c) short animated montage GIF (best-effort)
        set_job(job_id, stage="Rendering preview GIF", progress=48)
        try:
            gif_path = media.make_gif(video, info, workdir, base=safe)
        except Exception:  # noqa: BLE001 - gif is a bonus, never fail the job for it
            gif_path = None

        warnings = []

        # 3) assemble the release folder. For a single FILE, build a folder named
        #    after the file inside a dedicated packages directory OUTSIDE Cove's
        #    scanned library, HARDLINK the file into it (original stays put, Cove
        #    unaffected, no extra disk), put the contact sheet under screens/, and
        #    torrent that folder. If a hardlink isn't possible (e.g. the packages
        #    dir lands on a different disk), fall back to MOVING the file. A folder
        #    selection is torrented as-is.
        set_job(job_id, stage="Assembling release folder", progress=58)
        pkg_dir = None
        placed = None
        if os.path.isfile(selection):
            media_root = (CFG.get("media_roots") or ["/media"])[0]
            pkg_root = (CFG.get("packaging", {}).get("dir")
                        or os.path.join(media_root, "_full-release"))
            name = os.path.splitext(os.path.basename(selection))[0]
            pkg_dir = os.path.join(pkg_root, name)
            screens_dir = os.path.join(pkg_dir, "screens")
            try:
                os.makedirs(screens_dir, exist_ok=True)
                dest = os.path.join(pkg_dir, os.path.basename(selection))
                src_size = os.path.getsize(selection)
                if os.path.exists(dest):
                    placed = "exists"  # already packaged (re-run); reuse the folder
                else:
                    try:
                        os.link(selection, dest)          # hardlink - original stays put
                        placed = "hardlink"
                    except OSError:
                        shutil.move(selection, dest)      # fallback - move the file
                        placed = "move"
                    if not (os.path.exists(dest) and os.path.getsize(dest) == src_size):
                        raise RuntimeError("placed file failed size verification")
                # contact sheet goes inside the release under screens/
                shutil.copyfile(cs_path, os.path.join(screens_dir, os.path.basename(cs_path)))
                torrent_selection = pkg_dir
                if placed == "hardlink":
                    warnings.append(
                        "Hardlinked the file into " + pkg_dir + " - original left in place, "
                        "no extra disk used, Cove unaffected."
                    )
                elif placed == "move":
                    warnings.append(
                        "Hardlink wasn't possible (packages dir is on a different disk), so the "
                        "file was MOVED into " + pkg_dir + " - its path in Cove changed, rescan if needed."
                    )
            except Exception as e:  # noqa: BLE001 - never lose data; fall back to file-as-is
                warnings.append(f"Could not build the release folder ({e}); torrenting the file as-is.")
                pkg_dir = None
                torrent_selection = selection
        else:
            torrent_selection = selection

        # 4) torrent  (60-90%)  - covers the release folder (or the selection)
        set_job(job_id, stage="Hashing torrent", progress=60)
        tcfg = CFG.get("torrent", {})
        torrent_path = os.path.join(workdir, safe + ".torrent")
        tinfo = torrent_mod.create_torrent(
            torrent_selection,
            torrent_path,
            announce_url=tcfg.get("announce_url", ""),
            source=tcfg.get("source") or None,
            private=tcfg.get("private", True),
            comment=req.title,
            progress=lambda d, t: set_job(job_id, progress=60 + int(d / t * 30)),
        )
        warnings.extend(tinfo.pop("warnings", []))

        # 5) upload images  (90-96%)
        set_job(job_id, stage="Uploading images", progress=90)
        ih = CFG.get("imagehost", {})
        provider = ih.get("provider", "manual")

        def up(p):
            try:
                return imagehost.upload_image(p, provider, ih)
            except Exception as e:  # noqa: BLE001 - surface as a warning, don't fail the job
                warnings.append(f"Image upload failed for {os.path.basename(p)}: {e}")
                return f"UPLOAD_FAILED/{os.path.basename(p)}"

        uploaded = []  # [{label, name, url}] direct links to every hosted image

        def up_named(p, label):
            url = up(p)
            uploaded.append({"label": label, "name": os.path.basename(p), "url": url})
            return url

        cover_url = up_named(cover_path, "Cove thumbnail") if cover_path else None
        gif_url = up_named(gif_path, "Animated preview (GIF)") if gif_path else None
        cs_url = up_named(cs_path, "Contact sheet")
        preview_urls = [up_named(p, f"Preview {i + 1}") for i, p in enumerate(previews)]
        while len(preview_urls) < 2:
            preview_urls.append(cs_url)

        if provider == "manual":
            warnings.append(
                "Image host is 'manual' - the BBCode contains REPLACE_WITH_HOSTED_URL "
                "placeholders. Upload the saved images to your tracker-approved host and "
                "swap the URLs in."
            )

        # Collapse identical messages (e.g. a missing key reported once per image).
        warnings = list(dict.fromkeys(warnings))

        # 5) BBCode  (95-100%)
        set_job(job_id, stage="Rendering BBCode", progress=96)
        bcfg = CFG.get("bbcode", {})
        res_label = _resolution_label(info, req.resolution)
        perf_list = [p.strip() for p in (req.performers or "").split(",") if p.strip()]
        tags_line = build_tag_line(cove_tags, res_label, perf_list)
        ctx = {
            "title": req.title,
            "details": req.details,
            "performers": req.performers if bcfg.get("include_performers", True) else "",
            "file_type": req.file_type,
            "file_size": req.file_size,
            "duration": req.duration,
            "resolution": req.resolution,
            "preview1": preview_urls[0],
            "preview2": preview_urls[1],
            "contactsheet": cs_url,
            "cover": cover_url,
            "gif": gif_url,
        }
        tmpl_path = bcfg.get("template") or "app/templates/release.bbcode.j2"
        if not os.path.isabs(tmpl_path):
            tmpl_path = os.path.join(ROOT_DIR, tmpl_path)
        bb = bbcode.render_bbcode(tmpl_path, ctx)
        bb_path = os.path.join(workdir, safe + ".bbcode.txt")
        with open(bb_path, "w", encoding="utf-8") as f:
            f.write(bb)

        set_job(
            job_id,
            status="done",
            progress=100,
            stage="Complete",
            result={
                "workdir": workdir,
                "package_dir": pkg_dir,
                "torrent": torrent_path,
                "torrent_info": tinfo,
                "contact_sheet": cs_path,
                "contact_sheet_url": cs_url,
                "previews": previews,
                "preview_urls": preview_urls,
                "bbcode": bb,
                "bbcode_file": bb_path,
                "uploaded": uploaded,
                "tags_line": tags_line,
                "cover_url": cover_url,
                "gif_url": gif_url,
                "gif_file": gif_path,
                "warnings": warnings,
            },
        )
    except Exception as e:  # noqa: BLE001
        set_job(
            job_id,
            status="error",
            stage="Failed",
            error=f"{e}\n\n{traceback.format_exc()}",
        )
