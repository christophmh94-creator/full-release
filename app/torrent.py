"""Torrent creation using torf. Works on a single file or a whole folder.

Two limits below come straight from Luminance's own Torrent.php
(use_strict_bencode_specification): piece size over 8 MiB and any in-torrent
file path over 128 characters are both a hard `error()` - upload refused
outright, not auto-corrected like a missing private flag or wrong source tag.
torf's own default piece_size_max is 16 MiB, so without capping it a large
enough release silently produces a torrent Luminance will reject.
"""
from torf import Torrent

LUMINANCE_MAX_PIECE_SIZE = 8 * 1024 * 1024  # 8 MiB, Torrent.php hard cap
LUMINANCE_MAX_PATH_LEN = 128  # chars, per file, path relative to the torrent root


def create_torrent(path, out_path, announce_url="", source=None, private=True,
                   comment=None, progress=None):
    kwargs = {
        "path": path,
        "private": private,
        "created_by": "Full Release",
        "piece_size_max": LUMINANCE_MAX_PIECE_SIZE,
    }
    if announce_url:
        kwargs["trackers"] = [announce_url]
    if source:
        kwargs["source"] = source
    if comment:
        kwargs["comment"] = comment

    t = Torrent(**kwargs)

    def cb(torrent, filepath, pieces_done, pieces_total):
        if progress and pieces_total:
            progress(pieces_done, pieces_total)
        return None  # returning non-None aborts hashing

    t.generate(callback=cb, interval=0.5)
    t.write(out_path, overwrite=True)

    warnings = []
    if t.mode == "multifile":
        root_prefix = str(t.name) + "/"
        for f in t.files:
            rel = str(f)
            if rel.startswith(root_prefix):
                rel = rel[len(root_prefix):]
            if len(rel) > LUMINANCE_MAX_PATH_LEN:
                warnings.append(
                    f"File path is {len(rel)} chars, over Luminance's {LUMINANCE_MAX_PATH_LEN}-char "
                    f"limit and will be refused on upload: {rel}"
                )

    return {
        "path": out_path,
        "name": t.name,
        "infohash": t.infohash,
        "size": t.size,
        "piece_size": t.piece_size,
        "private": t.private,
        "source": getattr(t, "source", None),
        "warnings": warnings,
    }
