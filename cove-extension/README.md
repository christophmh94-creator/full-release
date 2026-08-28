# Open in Full Release (Cove extension)

Optional. Adds a single **Open in Full Release** button to the video detail
page in Cove. Clicking it resolves that video's file path through Cove's own
database and opens Full Release in a new tab with the file already selected,
so you land straight on Inspect.

Without it, Full Release still works: you just pick the file in its own
browser instead.

Nothing runs inside Cove. No job is queued, no work is done in the Cove
process. It is a lookup and a redirect.

## Layout

```
cove-extension/
├── refs/                          the four Cove DLLs go here, see refs/README.md
└── src/FullReleaseLink/
    ├── FullReleaseLink.csproj     net10.0, EnableDynamicLoading, host assemblies not copied
    ├── FullReleaseLinkExtension.cs  IActionExtension (the button) + IApiExtension (the lookup)
    ├── extension.json             manifest read by Cove's ExtensionManager
    └── frontend/
        └── open-in-full-release.mjs  client-side action handler that does window.open
```

## Build and deploy

Both are documented in [../docs/DEPLOY.md](../docs/DEPLOY.md). The short
version: drop the DLLs from your container into `refs/`, build with a
throwaway .NET 10 SDK container, copy the output plus `extension.json` and
`frontend/` into `<cove-config>/extensions/com.christophmh.full-release-link/`,
restart Cove.

## Two things worth knowing if you write your own

**Compile against your own container.** There is no published SDK package;
the assemblies come out of the running image and the contract moves between
versions. Concretely: in Cove 1.0.0 `CoveContext` was not resolvable from an
extension's child container and you had to go through the repository
interfaces in `Cove.Core/Interfaces/`. In 1.3.1 it resolves directly, which is
what this extension does.

**Authorize your own endpoints.** In the released build,
`ExtensionManager.RegisterExtensionEndpoints` maps extension endpoints without
applying any authorization policy, and Cove listens on `0.0.0.0`. A naively
mapped endpoint is therefore callable by anything on the network. This
extension checks `ICurrentPrincipalAccessor` and `IAuthorizationService`
explicitly in the handler and returns 401/403 itself. `RequiresPermission` does
not help: it is an MVC filter attribute and has no effect on minimal API
endpoints. Cove logs a warning about the missing policy on startup, which is
expected here rather than a sign something is wrong.
