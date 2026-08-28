# Deploying Full Release

This covers getting the container running. For what to put in `config.yaml`
once it's up, see [CONFIGURE.md](CONFIGURE.md). For the actual Select →
Inspect → Package workflow, see [USAGE.md](USAGE.md).

Full Release is a single Docker container with a built-in web GUI - no
database, no separate services. It talks to an already-running
[Cove](https://github.com/yourcove/cove) instance over HTTP for
metadata; nothing else is required at deploy time.

---

## Prerequisites

- A Docker host (this was built and is run on Unraid, but nothing here is
  Unraid-specific beyond the optional template).
- A **running Cove instance** reachable from the container over the network
  (LAN IP, not `localhost` - the two are separate containers).
- Your media library mounted somewhere the container can reach read-write
  (single-file packaging moves/hardlinks the file into a release folder next
  to itself).

Everything else (`ffmpeg`, `ffprobe`, fonts) is baked into the image by the
`Dockerfile`.

---

## Option A - Unraid

The image is built locally; you don't need a registry.

1. Copy this folder to the Unraid host, e.g. `/mnt/user/appdata/full-release-src/`.
2. Build the image on the host:
   ```sh
   cd /mnt/user/appdata/full-release-src/full-release
   docker build -t full-release:latest .
   ```
3. Add the container:
   - Copy `unraid-template.xml` to
     `/boot/config/plugins/dockerMan/templates-user/my-full-release.xml`, **or**
   - In the Unraid **Docker** tab → **Add Container** → fill in the same
     paths/ports shown in the template (WebUI port `8008`, `/config`,
     `/output`, `/media:rw`).
4. Adjust the host paths if your library isn't at `/mnt/user/torrent`, then
   **Apply**.
5. Open the WebUI. On first run it writes a starter `config.yaml` to
   `/mnt/user/appdata/full-release/config.yaml` - see
   [CONFIGURE.md](CONFIGURE.md) for what to put in it.

### Rebuilding after changes

> ⚠️ **A plain `docker restart` does *not* pick up a rebuilt image.** The
> container stays bound to whatever image ID it was created against, even if
> you `docker build` a new one under the same `:latest` tag. After rebuilding,
> you have to **recreate** the container:
>
> ```sh
> docker build -t full-release:latest .
> docker stop full-release && docker rm full-release
> docker run -d --name full-release --restart unless-stopped \
>   -p 8008:8080 \
>   -e COVE_URL=http://<cove-host>:5073 \
>   -v /mnt/user/torrent:/media:rw \
>   -v /mnt/user/appdata/full-release:/config \
>   -v /mnt/user/appdata/full-release/output:/output \
>   full-release:latest
> ```
>
> (Match the env vars / volumes to whatever you actually set up - the point is
> `stop` + `rm` + `run` again, not `restart`.) On Unraid, the Docker tab's
> **Force Update** does this for you if the container was added via a
> template.
>
> Verify you're actually on the new build:
> ```sh
> docker inspect full-release --format '{{.Image}}'
> docker images --no-trunc full-release:latest --format '{{.ID}}'
> ```
> These two IDs should match.

---

## Option B - docker compose

```sh
docker compose up -d --build
```

Edit `docker-compose.yml` first so `/mnt/user/torrent` points at your
library and `COVE_URL` points at your Cove instance. The GUI is then on
`http://<host>:8008/`. `docker compose up -d --build` *does* recreate the
container correctly (unlike a bare `docker restart`), so this option doesn't
have the gotcha above.

---

## Optional: the Cove "Open in Full Release" button

If you want the one-click flow described in [USAGE.md](USAGE.md) - clicking a
button on a video's page in Cove and landing in Full Release with that file
already selected - you need a small **Cove extension** alongside the main
container. This is optional; without it you just use the file browser inside
Full Release directly.

The extension:

- Adds a button to the video detail page toolbar in Cove.
- On click, resolves the video's file path via Cove's own database and opens
  Full Release in a new tab with `?path=...` set, which auto-selects the file
  and jumps straight to Inspect.
- Runs entirely client-side plus one small server endpoint inside Cove; no
  job queue, no background work.

### Building it

Cove extensions are compiled **against the DLLs of your specific running
Cove container**, not against a source checkout - the API surface differs
between versions and there's no compatibility guarantee across them. General
pattern:

```sh
mkdir -p full-release-link-build/refs full-release-link-build/src/FullReleaseLink

# Pull the exact DLLs your Cove container is running
for f in Cove.Sdk.dll Cove.Plugins.dll Cove.Core.dll Cove.Data.dll; do
  docker cp Cove:/opt/cove/$f full-release-link-build/refs/$f
done

# Build (needs the .NET 10 SDK - a throwaway container is enough)
docker run --rm -v "$PWD/full-release-link-build:/work" \
  -w /work/src/FullReleaseLink mcr.microsoft.com/dotnet/sdk:10.0 \
  bash -c "dotnet build -c Release -o /work/out"
```

The extension's own source (`.csproj`, the extension class, `extension.json`,
and a small `frontend/*.mjs` handler that does the actual `window.open`) isn't
included in this repository - it's Cove-specific glue code, not part of Full
Release itself. If you're rebuilding it, the project needs:

- `IActionExtension` - registers the toolbar button (`ActionType: "toolbar"`,
  `EntityTypes: ["video"]`, a `HandlerName` so the click resolves to a
  client-side JS handler instead of the default POST-and-toast behavior,
  since opening a new tab needs to happen in the browser).
- `IApiExtension` - one endpoint that looks up `Video.MaxPath`, maps it from
  Cove's mount point to Full Release's, and returns the target URL as JSON.
- A `frontend/*.mjs` file exporting `{ actionHandlers: { open: async (action, payload) => {...} } }`
  that calls that endpoint and does `window.open(url, "_blank")`.

### Deploying it

```sh
mkdir -p /path/to/cove/config/extensions/com.example.full-release-link/frontend
cp full-release-link-build/out/FullReleaseLink.dll \
   full-release-link-build/out/FullReleaseLink.deps.json \
   /path/to/cove/config/extensions/com.example.full-release-link/
cp extension.json /path/to/cove/config/extensions/com.example.full-release-link/
cp frontend/open-in-full-release.mjs \
   /path/to/cove/config/extensions/com.example.full-release-link/frontend/

docker restart Cove
```

Check the Cove container logs after restart - a clean load looks like:

```
[FullReleaseLink] Full Release Link 1.0.0 initialised, target http://<host>:8008.
[Cove.Plugins.ExtensionManager] Extension com.example.full-release-link (Open in Full Release v1.0.0) initialized
```

A warning about the endpoint having "no Cove authorization policy" is
expected and harmless as long as the extension does its own auth check
inside the handler (verify with an unauthenticated `curl -X POST` against the
endpoint - it should come back `401`, not succeed).

The base URL the extension points at is controlled by a `FULL_RELEASE_URL`
environment variable on the Cove container (defaults to a hardcoded fallback
in the extension code) - set it if Full Release isn't reachable at the
default the extension was built with.

### File path mapping

Cove and Full Release almost certainly don't mount your media library at the
same container path. The extension has to translate between them - e.g. if
Cove sees a file at `/media/torrent/foo.mp4` (because Cove mounts your whole
share) and Full Release only mounts the `torrent` subfolder as its own
`/media`, the extension strips the `torrent/` prefix and re-adds Full
Release's own root. Check both containers' actual mounts before assuming a
mapping:

```sh
docker inspect Cove --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'
docker inspect full-release --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}'
```

---

## Verifying the deployment

```sh
curl -s http://localhost:8008/api/config | python3 -m json.tool
```

Look for `"cove_ok": true`. If it's `false`, Full Release can reach the
`cove.url` but auth failed or Cove itself returned an error - check
`cove.username`/`cove.password`/`cove.api_key`. If `cove_configured` is
`false`, `cove.url` itself isn't set.
