"""ffmpeg/ffprobe driven media analysis and contact-sheet generation."""
import json
import math
import os
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def human_size(num):
    num = float(num or 0)
    for unit in ["B", "KiB", "MiB", "GiB", "TiB"]:
        if num < 1024 or unit == "TiB":
            if unit in ("B", "KiB"):
                return f"{int(num)} {unit}"
            return f"{num:.2f} {unit}"
        num /= 1024
    return f"{num:.2f} TiB"


def fmt_duration(sec):
    sec = int(sec or 0)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m {s:02d}s"


def fmt_timecode(sec):
    sec = int(sec or 0)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _parse_fps(s):
    try:
        n, d = str(s).split("/")
        d = float(d)
        return float(n) / d if d else 0.0
    except Exception:
        return 0.0


def ffprobe_info(path):
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", path,
    ]
    p = _run(cmd)
    try:
        data = json.loads(p.stdout or "{}")
    except json.JSONDecodeError:
        data = {}
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    a = next((s for s in streams if s.get("codec_type") == "audio"), {})
    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or v.get("duration") or 0)
    size = int(fmt.get("size") or (os.path.getsize(path) if os.path.exists(path) else 0))
    return {
        "duration": duration,
        "size": size,
        "width": int(v.get("width") or 0),
        "height": int(v.get("height") or 0),
        "video_codec": v.get("codec_name") or "",
        "audio_codec": a.get("codec_name") or "",
        "frame_rate": round(_parse_fps(v.get("avg_frame_rate") or v.get("r_frame_rate") or "0/0"), 3),
        "format": (fmt.get("format_name") or "").split(",")[0],
        "bit_rate": int(fmt.get("bit_rate") or 0),
    }


def _font(size):
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def extract_frame(path, ts, out_path, width=None):
    vf = f"scale={width}:-2" if width else "scale=iw:ih"
    cmd = [
        "ffmpeg", "-y", "-ss", f"{max(ts, 0):.3f}", "-i", path,
        "-frames:v", "1", "-vf", vf, "-q:v", "3", out_path,
    ]
    _run(cmd)
    return os.path.exists(out_path) and os.path.getsize(out_path) > 0


def _header_lines(path, info):
    return [
        f"File:  {os.path.basename(path)}",
        (
            f"Size: {human_size(info.get('size', 0))}    "
            f"Duration: {fmt_timecode(info.get('duration', 0))}    "
            f"Resolution: {info.get('width', 0)}x{info.get('height', 0)}    "
            f"Codec: {info.get('video_codec', '')}"
        ),
    ]


def make_contact_sheet(path, info, out_path, cols=4, rows=5, thumb_width=480,
                       header=True, progress=None):
    n = max(cols * rows, 1)
    duration = info.get("duration") or 0

    if duration <= 0:
        # No usable duration (e.g. corrupt header) - fall back to a single frame.
        if not extract_frame(path, 1, out_path, thumb_width * cols):
            raise RuntimeError("Could not extract any frame from the video")
        return out_path

    start = duration * 0.02
    end = duration * 0.98
    step = (end - start) / max(n - 1, 1)
    timestamps = [start + i * step for i in range(n)]

    tmpdir = tempfile.mkdtemp(prefix="cs_")
    frames = []
    for i, ts in enumerate(timestamps):
        fp = os.path.join(tmpdir, f"f{i:03d}.jpg")
        if extract_frame(path, ts, fp, thumb_width):
            frames.append((ts, fp))
        if progress:
            progress(i + 1, n)

    if not frames:
        raise RuntimeError("No frames extracted for the contact sheet")

    with Image.open(frames[0][1]) as im0:
        tw, th = im0.size

    pad = 4
    grid_cols = cols
    grid_rows = math.ceil(len(frames) / grid_cols)
    sheet_w = grid_cols * tw + (grid_cols + 1) * pad

    header_lines = _header_lines(path, info) if header else []
    header_h = (12 + 24 * len(header_lines)) if header_lines else 0

    sheet_h = header_h + grid_rows * th + (grid_rows + 1) * pad
    sheet = Image.new("RGB", (sheet_w, sheet_h), (22, 24, 28))
    draw = ImageDraw.Draw(sheet)

    if header_lines:
        hf = _font(18)
        y = 8
        for line in header_lines:
            draw.text((pad + 4, y), line, font=hf, fill=(222, 226, 232))
            y += 24

    tf = _font(16)
    for idx, (ts, fp) in enumerate(frames):
        r, c = divmod(idx, grid_cols)
        x = pad + c * (tw + pad)
        y = header_h + pad + r * (th + pad)
        with Image.open(fp) as im:
            sheet.paste(im, (x, y))
        label = fmt_timecode(ts)
        tx, ty = x + 6, y + th - 24
        draw.text((tx + 1, ty + 1), label, font=tf, fill=(0, 0, 0))
        draw.text((tx, ty), label, font=tf, fill=(255, 255, 255))

    sheet.save(out_path, "JPEG", quality=88)
    return out_path


def make_previews(path, info, out_dir, count=2, width=960, base=None):
    duration = info.get("duration") or 0
    points = []
    if duration > 0:
        for i in range(count):
            points.append(duration * ((i + 1) / (count + 1)))
    else:
        points = [1.0] * count

    # Name the previews after the actual video so the image host shows a
    # meaningful filename instead of "preview1"/"preview2".
    stem = base or os.path.splitext(os.path.basename(path))[0]

    out = []
    for i, ts in enumerate(points):
        fp = os.path.join(out_dir, f"{stem}_preview_{i + 1:02d}.jpg")
        if extract_frame(path, ts, fp, width):
            out.append(fp)
    return out


def make_gif(path, info, out_dir, base=None, segments=6, seg_len=0.8,
             fps=8, width=420, progress=None):
    """Short animated montage GIF: `segments` short clips sampled evenly across
    the whole video, concatenated, palette-optimised. Named after the file.
    Returns the gif path, or None if it couldn't be produced."""
    stem = base or os.path.splitext(os.path.basename(path))[0]
    out_path = os.path.join(out_dir, f"{stem}_preview.gif")
    duration = info.get("duration") or 0

    def _try(cmd):
        _run(cmd)
        return os.path.exists(out_path) and os.path.getsize(out_path) > 0

    if duration and duration > (seg_len * 2):
        start, end = 0.05 * duration, 0.95 * duration
        step = (end - start - seg_len) / max(segments - 1, 1)
        ts = [start + i * step for i in range(segments)]
        trims = ";".join(
            f"[0:v]trim=start={t:.2f}:end={t + seg_len:.2f},setpts=PTS-STARTPTS[v{i}]"
            for i, t in enumerate(ts)
        )
        cat = "".join(f"[v{i}]" for i in range(segments))
        flt = (
            f"{trims};{cat}concat=n={segments}:v=1[c];"
            f"[c]fps={fps},scale={width}:-2:flags=lanczos,split[a][b];"
            f"[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer"
        )
        if progress:
            progress(1, 2)
        if _try(["ffmpeg", "-y", "-i", path, "-filter_complex", flt, "-loop", "0", out_path]):
            if progress:
                progress(2, 2)
            return out_path

    # Fallback: a single short clip from ~40% through the file.
    mid = (duration * 0.4) if duration else 1.0
    flt = f"fps={fps},scale={width}:-2:flags=lanczos"
    if _try(["ffmpeg", "-y", "-ss", f"{mid:.2f}", "-t", "2.5", "-i", path,
             "-vf", flt, "-loop", "0", out_path]):
        if progress:
            progress(2, 2)
        return out_path
    return None
