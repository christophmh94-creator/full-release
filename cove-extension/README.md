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

**Authorize your own endpoints.** Extension endpoints default to anonymous
access for backward compatibility, and Cove listens on `0.0.0.0`, so an
endpoint that declares nothing is callable by anything on the network. Cove
1.3.x lets you declare intent on the endpoint itself with
`RequireCovePermission`, `RequireCoveEntityAccess`,
`AllowWithoutCovePermission` or `AllowCoveAnonymous`, and warns at startup
about endpoints that declare none.

This extension predates that and instead checks `ICurrentPrincipalAccessor`
and `IAuthorizationService` by hand in the handler, returning 401/403 itself.
That works, and you can verify it with an unauthenticated `curl -X POST`
against the endpoint, but declaring the requirement is the better way round.
Moving it over is an open follow-up here. What does not work either way is
`RequiresPermission`: it is an MVC filter attribute and minimal API endpoints
ignore it.
