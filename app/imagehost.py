"""Image upload. Pluggable so the tracker-approved host can be wired up in config.

Providers:
- "chevereto": uploads to a Chevereto V4 instance (this is what hamsterimg.net runs)
  via its API V1 endpoint POST {url}/api/1/upload. Returns the direct image URL.
- "imgbb":     uploads to imgbb.com using an API key. Confirm imgbb is acceptable on
  your tracker before using it for real uploads.
- "manual":    no upload. Returns a placeholder the user replaces after uploading the
  saved image to their preferred (tracker-approved) host.
"""
import base64
import os

import requests


def upload_image(path, provider="manual", config=None):
    config = config or {}
    provider = (provider or "manual").lower()

    if provider == "chevereto":
        return _chevereto(
            path,
            url=config.get("chevereto_url"),
            api_key=config.get("chevereto_api_key"),
            nsfw=config.get("nsfw", True),
        )

    if provider == "imgbb":
        return _imgbb(path, config.get("imgbb_api_key"))

    # manual / unknown -> placeholder
    return f"REPLACE_WITH_HOSTED_URL/{os.path.basename(path)}"


def _chevereto(path, url, api_key, nsfw=True):
    """Upload to a Chevereto V4 instance (API V1) and return the direct image URL."""
    if not url:
        raise RuntimeError(
            "imagehost.provider is 'chevereto' but chevereto_url is empty"
        )
    if not api_key:
        raise RuntimeError(
            "imagehost.provider is 'chevereto' but chevereto_api_key is empty"
        )

    endpoint = url.rstrip("/") + "/api/1/upload"
    headers = {"X-API-Key": api_key}
    data = {"format": "json", "nsfw": "1" if nsfw else "0"}

    with open(path, "rb") as f:
        files = {"source": (os.path.basename(path), f, "application/octet-stream")}
        r = requests.post(
            endpoint, headers=headers, data=data, files=files, timeout=180
        )

    # Chevereto returns a JSON body on success AND on most errors; prefer its message.
    try:
        payload = r.json()
    except ValueError:
        r.raise_for_status()
        raise RuntimeError(f"Chevereto returned a non-JSON response (HTTP {r.status_code})")

    if isinstance(payload, dict) and payload.get("status_code") == 200:
        img = payload.get("image") or {}
        direct = (
            img.get("url")
            or img.get("display_url")
            or (img.get("image") or {}).get("url")
        )
        if direct:
            return direct
        raise RuntimeError("Chevereto upload succeeded but no image URL was found in the response")

    # Error path: surface the tracker host's own message.
    msg = None
    if isinstance(payload, dict):
        err = payload.get("error") or {}
        msg = err.get("message") or payload.get("status_txt")
    raise RuntimeError(f"Chevereto upload failed (HTTP {r.status_code}): {msg or 'unknown error'}")


def _imgbb(path, api_key):
    if not api_key:
        raise RuntimeError("imagehost.provider is 'imgbb' but imgbb_api_key is empty")
    with open(path, "rb") as f:
        payload = base64.b64encode(f.read()).decode()
    r = requests.post(
        "https://api.imgbb.com/1/upload",
        data={
            "key": api_key,
            "image": payload,
            "name": os.path.splitext(os.path.basename(path))[0],
        },
        timeout=120,
    )
    r.raise_for_status()
    data = r.json()
    return data["data"]["url"]
